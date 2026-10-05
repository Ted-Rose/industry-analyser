"""Re-fetch cv.lv vacancy detail pages to refresh stored rows
(docs/vacancy_refetch_plan.md).

Unlike the incremental scrape — which only fills empty fields and
only ever *adds* keyword links — this command performs a true
refresh per selected vacancy: mutable fields are overwritten from
the fresh detail payload, keyword/industry links that no longer
match are removed, and the linked Company is re-enriched
(about/contacts/reg_code) via ``company_linking``.

Instantiates VacancyScrapper purely for its throttled
``make_request`` + ``_extract_next_data`` + ``_build_vacancy`` —
``run()`` is never called (same trick as
``link_vacancies_to_companies``).

Usage:
    python manage.py refetch_vacancies --keyword-id 12 --dry-run
    python manage.py refetch_vacancies --keyword-id 12 \
        --exclude-keywords 30 31 --limit 50
    python manage.py refetch_vacancies --ids 1655039 1655040 \
        --no-ocr
"""
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from fetcher import company_linking
from fetcher.management.commands.link_vacancies_to_companies import (
    nextjs_portal_id,
)
from fetcher.models import (
    Keyword,
    Vacancy,
    VacancyContainsKeyword,
    VacancyFile,
    VacancyIndustries,
)
from fetcher.scraper import VacancyScrapper

logger = logging.getLogger('fetcher')

# Scalar fields overwritten only when the fresh payload carries a
# value — a partial detail object must not blank identity fields.
KEEP_IF_EMPTY = ('title', 'company_name', 'first_seen')
# Scalar fields overwritten unconditionally: the detail payload is
# the source of truth, so a salary/deadline the ad no longer
# reports must be cleared.
ALWAYS_OVERWRITE = (
    'salary_from', 'salary_to', 'application_deadline'
)


class Command(BaseCommand):
    help = (
        'Re-fetch vacancy detail pages and refresh vacancy fields, '
        'company data, keyword links and OCR text.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--keyword-id', type=int, default=None,
            help='Refetch vacancies linked to this Keyword id '
                 '(required unless --ids is given).',
        )
        parser.add_argument(
            '--exclude-keywords', nargs='+', type=int, default=None,
            help='Skip vacancies linked to ANY of these Keyword '
                 'ids.',
        )
        parser.add_argument(
            '--ids', nargs='+', type=int, default=None,
            help='Only these vacancy_portal_ids — bypasses '
                 'keyword selection.',
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help='Max vacancies to process.',
        )
        parser.add_argument(
            '--batch-size', type=int, default=100,
            help='Rows fetched per query batch (default: 100).',
        )
        parser.add_argument(
            '--no-ocr', action='store_true',
            help='Skip fetching/AI-transcribing attached files; '
                 'cached VacancyFile text is still reused.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print matching row counts and first ~10 '
                 'vacancies — no fetches, no writes.',
        )

    def handle(self, *args, **options):
        if options['batch_size'] < 1:
            raise CommandError('--batch-size must be >= 1.')
        if not options['ids'] and options['keyword_id'] is None:
            raise CommandError(
                '--keyword-id is required unless --ids is given.'
            )
        self._validate_keyword_ids(options)
        portal_id = nextjs_portal_id()
        if portal_id is None:
            raise CommandError(
                'No configured portal with type "nextjs" — detail '
                'pages only exist on the public cv.lv portal.'
            )
        qs = self._select_vacancies(options)
        if options['limit']:
            qs = qs[:options['limit']]
        total = qs.count()
        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] {total} vacancy(ies) would be '
                f'detail-fetched and refreshed'
            ))
            for vacancy in qs[:10]:
                self.stdout.write(
                    f'  {vacancy.vacancy_portal_id} '
                    f'{vacancy.title}'
                )
            return
        scraper = VacancyScrapper(portal_id=portal_id)
        if options['no_ocr']:
            # _ocr_vacancy_file still reuses cached VacancyFile
            # text but never fetches the file or calls the AI.
            scraper._ocr_unavailable = True
        self._refetch_all(scraper, qs, total, options)

    def _validate_keyword_ids(self, options):
        keyword_ids = set(options['exclude_keywords'] or [])
        if options['keyword_id'] is not None:
            keyword_ids.add(options['keyword_id'])
        if not keyword_ids:
            return
        found = set(
            Keyword.objects.filter(id__in=keyword_ids)
            .values_list('id', flat=True)
        )
        missing = sorted(keyword_ids - found)
        if missing:
            raise CommandError(
                f'Unknown keyword id(s): {missing}'
            )

    def _select_vacancies(self, options):
        if options['ids']:
            qs = Vacancy.objects.filter(
                vacancy_portal_id__in=options['ids']
            ).order_by('vacancy_portal_id')
            found = set(qs.values_list('vacancy_portal_id',
                                       flat=True))
            missing = sorted(set(options['ids']) - found)
            if missing:
                self.stdout.write(self.style.WARNING(
                    f'{len(missing)} vacancy_portal_id(s) not '
                    f'found in DB: {missing}'
                ))
            return qs
        qs = Vacancy.objects.filter(
            keywords__id=options['keyword_id']
        )
        excluded = options['exclude_keywords'] or []
        if excluded:
            # Explicit subquery — chaining
            # .exclude(keywords__id__in=...) onto the same
            # relation would alias-confuse with the include.
            qs = qs.exclude(
                pk__in=Vacancy.objects.filter(
                    keywords__id__in=excluded
                )
            )
        # Stalest detail first — rows never detail-fetched lead.
        return qs.order_by(
            F('detail_fetched_at').asc(nulls_first=True)
        )

    def _refetch_all(self, scraper, qs, total, options):
        counts = {
            'refreshed': 0,
            'no_employer': 0,
            'fetch_failed': 0,
            'no_detail': 0,
            'error': 0,
            'companies': 0,
            'files_seen': 0,
            'files_saved': 0,
            'keywords_changed': 0,
            'industries_changed': 0,
        }
        done = 0
        for vacancy in qs.iterator(
            chunk_size=options['batch_size']
        ):
            outcome = self._refetch_one(scraper, vacancy, counts)
            counts[outcome] += 1
            if outcome != 'refreshed':
                logger.info(
                    f"Vacancy {vacancy.vacancy_portal_id}: "
                    f"{outcome}"
                )
            done += 1
            if done % options['batch_size'] == 0:
                self.stdout.write(f'  ... processed {done}/{total}')
        message = (
            f'{done} vacancy(ies) processed: '
            + ', '.join(
                f'{k}={v}' for k, v in sorted(counts.items())
            )
        )
        logger.info('refetch_vacancies: %s', message)
        self.stdout.write(self.style.SUCCESS(f'done: {message}'))

    def _refetch_one(self, scraper, vacancy, counts):
        """Fetch + refresh one vacancy; returns its outcome key.
        One bad row must not kill the run."""
        try:
            response = scraper.make_request(vacancy.url)
            if response is None:
                return 'fetch_failed'
            data = scraper._extract_next_data(response.data)
            detail = company_linking.extract_vacancy_detail(
                data, vacancy.vacancy_portal_id
            )
            if detail is None:
                # Expired/deleted ads lose their detail JSON.
                return 'no_detail'
            details = detail.get('details') or {}
            if (details.get('fileDetails') or {}).get('fileId'):
                counts['files_seen'] += 1
            fresh = self._build_fresh(scraper, vacancy, detail)
            if fresh is None:
                return 'error'
            with transaction.atomic():
                return self._apply_fresh(
                    vacancy, fresh, timezone.now(), counts
                )
        except Exception:
            logger.exception(
                f"Refetch failed for vacancy "
                f"{vacancy.vacancy_portal_id}"
            )
            return 'error'

    def _build_fresh(self, scraper, vacancy, detail):
        """Run the fresh detail payload through
        ``VacancyScrapper._build_vacancy`` so keyword matching, OCR
        staging, industry mapping and employer slicing are identical
        to a live scrape. Returns an unsaved Vacancy."""
        result = dict(detail)
        result['id'] = vacancy.vacancy_portal_id
        # Seed stored values for fields the detail object may not
        # carry — they still feed keyword matching.
        if not result.get('positionTitle'):
            result['positionTitle'] = vacancy.title
        if not result.get('employerName'):
            result['employerName'] = vacancy.company_name
        result['_detail'] = detail
        return scraper.initiate_resource(result)

    def _apply_fresh(self, vacancy, fresh, now, counts):
        """Rewrite ``vacancy`` from the freshly built row inside
        the caller's transaction."""
        outcome = 'refreshed'
        employer_slice = getattr(
            fresh, '_pending_employer_detail', None
        )
        if (employer_slice or {}).get('employer_id') is None:
            outcome = 'no_employer'
        else:
            company = company_linking.resolve_company(
                employer_slice['employer_id'],
                employer_slice['employer_name'],
                now=now,
            )
            company_linking.apply_employer_detail(
                company, employer_slice, now=now
            )
            vacancy.company = company
            counts['companies'] += 1
        for field in KEEP_IF_EMPTY:
            value = getattr(fresh, field)
            if value is not None:
                setattr(vacancy, field, value)
        for field in ALWAYS_OVERWRITE:
            setattr(vacancy, field, getattr(fresh, field))
        vacancy.last_seen = now
        vacancy.detail_fetched_at = now
        vacancy.save()
        if self._replace_links(
            vacancy, VacancyContainsKeyword, 'keyword_id',
            {k.id for k in getattr(fresh, '_pending_keywords', [])},
        ):
            counts['keywords_changed'] += 1
        if self._replace_links(
            vacancy, VacancyIndustries, 'industry_id',
            {i.id for i in
             getattr(fresh, '_pending_industries', [])},
        ):
            counts['industries_changed'] += 1
        vacancy_file = getattr(fresh, '_pending_file', None)
        if vacancy_file is not None:
            _, created = VacancyFile.objects.get_or_create(
                file_id=vacancy_file.file_id,
                defaults={
                    'vacancy': vacancy,
                    'content_type': vacancy_file.content_type,
                    'sha256': vacancy_file.sha256,
                    'extracted_text': vacancy_file.extracted_text,
                    'ai_model': vacancy_file.ai_model,
                    'ai_request': vacancy_file.ai_request,
                },
            )
            if created:
                counts['files_saved'] += 1
        return outcome

    @staticmethod
    def _replace_links(vacancy, model, fk_field, new_ids):
        """Swap a vacancy's M2M through-rows for ``new_ids`` —
        unlike the incremental scrape, a refresh removes links
        that no longer match. Returns True when the set changed."""
        existing = set(
            model.objects.filter(vacancy=vacancy)
            .values_list(fk_field, flat=True)
        )
        if existing == new_ids:
            return False
        model.objects.filter(vacancy=vacancy).delete()
        model.objects.bulk_create([
            model(vacancy_id=vacancy.pk, **{fk_field: rel_id})
            for rel_id in new_ids
        ])
        return True

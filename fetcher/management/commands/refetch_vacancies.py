"""Re-fetch cv.lv vacancy detail pages to refresh stored rows
(docs/vacancy_refetch_plan.md).

Unlike the incremental scrape — which only fills empty fields and
only ever *adds* keyword links — this command performs a true
refresh per selected vacancy: the detail payload is normalized
into search-result shape (``position`` → ``positionTitle``,
``highlights.salary*`` → ``salary*``, ``settings.dateTo`` →
``application_deadline`` …), mutable fields are overwritten when
the payload actually reports them, keyword links that no longer
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
    python manage.py refetch_vacancies --keyword-id 12 \
        --first-seen-after 2026-09-01 --offset 300
    python manage.py refetch_vacancies --ids 1655039 1655040 \
        --no-ocr
"""
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

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
# (first_seen is deliberately absent: it records when *we* first
# saw the ad, not the portal's publish date.)
KEEP_IF_EMPTY = ('title', 'company_name')
# Scalar fields overwritten only when the detail payload actually
# carried the source key (``_overwritable_fields``): an explicit
# null clears the stored value, but a missing key means "the
# portal didn't report it this time" and the stored value is
# kept.
OVERWRITE_IF_PRESENT = (
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
            '--offset', type=int, default=None,
            help='Skip the first N vacancies of the ordered '
                 'result set — --offset 300 starts at the '
                 '301st (applied before --limit).',
        )
        parser.add_argument(
            '--first-seen-after', metavar='DATE', default=None,
            help='Only vacancies first spotted on or after '
                 'this date (YYYY-MM-DD or ISO datetime).',
        )
        parser.add_argument(
            '--first-seen-before', metavar='DATE', default=None,
            help='Only vacancies first spotted on or before '
                 'this date (YYYY-MM-DD or ISO datetime).',
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
        if options['limit'] is not None and options['limit'] < 1:
            raise CommandError('--limit must be >= 1.')
        if options['offset'] is not None and options['offset'] < 0:
            raise CommandError('--offset must be >= 0.')
        if options['ids'] and (
            options['keyword_id'] is not None
            or options['exclude_keywords']
            or options['first_seen_after']
            or options['first_seen_before']
        ):
            raise CommandError(
                '--ids bypasses keyword selection — do not '
                'combine it with --keyword-id, '
                '--exclude-keywords or --first-seen-*.'
            )
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
        if options['offset']:
            qs = qs[options['offset']:]
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
        qs = self._apply_first_seen_filters(qs, options)
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
        # Stalest detail first — rows never detail-fetched
        # lead. The pk tiebreaker keeps ties deterministic so
        # --offset resumes predictably (equal detail_fetched_at
        # values — above all the NULLs — have no natural order).
        return qs.order_by(
            F('detail_fetched_at').asc(nulls_first=True), 'pk'
        )

    @staticmethod
    def _apply_first_seen_filters(qs, options):
        """Apply --first-seen-after/--first-seen-before. Plain
        dates compare against ``first_seen__date`` so a boundary
        day covers that whole day; full ISO datetimes compare
        directly. Both bounds are inclusive."""
        for flag, op in (
            ('first_seen_after', 'gte'),
            ('first_seen_before', 'lte'),
        ):
            raw = options[flag]
            if raw is None:
                continue
            parsed = parse_date(raw)
            if parsed is not None:
                qs = qs.filter(
                    **{f'first_seen__date__{op}': parsed}
                )
                continue
            parsed = parse_datetime(raw)
            if parsed is None:
                raise CommandError(
                    f"--{flag.replace('_', '-')} must be a "
                    f"date (YYYY-MM-DD) or ISO datetime — "
                    f"got {raw!r}."
                )
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            qs = qs.filter(**{f'first_seen__{op}': parsed})
        return qs

    def _refetch_all(self, scraper, qs, total, options):
        counts = {
            'refreshed': 0,
            'no_employer': 0,
            'fetch_failed': 0,
            'no_next_data': 0,
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
            logger.info(
                f"Vacancy {vacancy.vacancy_portal_id} "
                f"{vacancy.url}: {outcome}"
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
            if data is None:
                # Malformed page — no __NEXT_DATA__ blob at all.
                return 'no_next_data'
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

    @staticmethod
    def _aware_iso(value):
        """Re-serialize a portal date string as aware ISO — detail
        dates are date-only ('2026-10-10') and parse naive, but
        Vacancy datetimes must be timezone-aware."""
        if not value:
            return None
        parsed = parse_datetime(str(value))
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed.isoformat()

    def _build_fresh(self, scraper, vacancy, detail):
        """Normalize the detail payload into search-result shape,
        then run it through ``VacancyScrapper._build_vacancy`` so
        keyword matching, OCR staging, industry mapping and
        employer slicing are identical to a live scrape. Returns
        an unsaved Vacancy.

        The detail object nests what the search payload keeps
        flat: the title under ``position``, salaries under
        ``highlights``, the deadline under ``settings.dateTo``,
        declared keywords as ``settings.keywords`` {id, value}
        dicts and categories as ``settings.categories`` enum
        names. ``fresh._overwritable_fields`` records which
        OVERWRITE_IF_PRESENT sources the payload actually
        carried — key *presence*, not truthiness, is what allows
        a stored value to be cleared.
        """
        highlights = detail.get('highlights') or {}
        portal_settings = detail.get('settings') or {}
        result = dict(detail)
        result['id'] = vacancy.vacancy_portal_id
        # Seed stored values as fallbacks — they still feed
        # keyword matching when the payload lacks a field.
        result['positionTitle'] = (
            detail.get('position') or highlights.get('position')
            or vacancy.title
        )
        result['employerName'] = (
            detail.get('employerName') or vacancy.company_name
        )
        result['salaryFrom'] = highlights.get('salaryFrom')
        result['salaryTo'] = highlights.get('salaryTo')
        result['expirationDate'] = self._aware_iso(
            portal_settings.get('dateTo')
        )
        # Categories arrive as enum names ('INFORMATION_TECHNOLOGY'),
        # not the numeric ids industry_mapping understands — they
        # only link when the mapping/Industry rows know them.
        result['categories'] = (
            portal_settings.get('categories') or []
        )
        result['keywords'] = [
            keyword['value']
            for keyword in portal_settings.get('keywords') or []
            if keyword.get('value')
        ]
        result['_detail'] = detail
        fresh = scraper.initiate_resource(result)
        fresh._overwritable_fields = set()
        if 'salaryFrom' in highlights:
            fresh._overwritable_fields.add('salary_from')
        if 'salaryTo' in highlights:
            fresh._overwritable_fields.add('salary_to')
        if 'dateTo' in portal_settings:
            fresh._overwritable_fields.add('application_deadline')
        return fresh

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
        overwritable = getattr(fresh, '_overwritable_fields', ())
        for field in OVERWRITE_IF_PRESENT:
            if field in overwritable:
                setattr(vacancy, field, getattr(fresh, field))
        vacancy.last_seen = now
        vacancy.detail_fetched_at = now
        vacancy.save()
        if self._replace_links(
            vacancy, VacancyContainsKeyword, 'keyword_id',
            {k.id for k in getattr(fresh, '_pending_keywords', [])},
        ):
            counts['keywords_changed'] += 1
        pending_industries = {
            i.id for i in getattr(fresh, '_pending_industries', [])
        }
        # Detail categories are enum names industry_mapping can't
        # resolve, so a detail fetch normally yields no industries
        # — only swap links when fresh ones were actually
        # produced, otherwise the stored set stays.
        if pending_industries and self._replace_links(
            vacancy, VacancyIndustries, 'industry_id',
            pending_industries,
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

"""Link vacancies to canonical Company rows by re-fetching their
public detail pages (docs/company_linking_plan.md PR-4).

Vacancies scraped before company linking existed carry no
employerId, so each row needs one throttled detail fetch — the
``employer`` object in ``__NEXT_DATA__`` is the only public source
of regCode/about/contacts. Rows that never yield a detail page
(expired ads) keep ``company`` null, so the command is
self-resuming via the null-FK predicate.

Instantiates VacancyScrapper purely for its throttled
``make_request`` + ``_extract_next_data`` — ``run()`` is never
called (same trick as ``enrich_tv_shows``).

Usage:
    python manage.py link_vacancies_to_companies --dry-run
    python manage.py link_vacancies_to_companies --limit 500
    python manage.py link_vacancies_to_companies --ids 1655039 ...
    python manage.py link_vacancies_to_companies --employers-only \
        --stale-days 7 --limit 200
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Q
from django.utils import timezone

from fetcher import company_linking
from fetcher.models import Company, Vacancy
from fetcher.scraper import VacancyScrapper, load_portals_config

logger = logging.getLogger('fetcher')

# Detail-page attempts per company in --employers-only mode; a
# company's freshest vacancies are tried first, this bounds the
# requests spent on companies whose ads are all dead.
MAX_VACANCY_ATTEMPTS = 3


def nextjs_portal_id():
    """First configured portal with ``type: 'nextjs'`` (config
    ``order`` ascending, numeric key tiebreak)."""
    portals = load_portals_config()
    ordered = sorted(
        portals,
        key=lambda pid: (
            int(portals[pid].get('order', pid)), int(pid)
        ),
    )
    for pid in ordered:
        if portals[pid].get('type') == 'nextjs':
            return int(pid)
    return None


class Command(BaseCommand):
    help = (
        'Link vacancies to Company rows via detail-page fetches '
        '(self-resuming: only company IS NULL rows are targeted).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--ids', nargs='+', type=int, default=None,
            help='Only these vacancy_portal_ids (relinks even '
                 'already-linked rows).',
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help='Max vacancies (or companies with '
                 '--employers-only) to process.',
        )
        parser.add_argument(
            '--batch-size', type=int, default=500,
            help='Rows fetched per query batch (default: 500).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print matching row counts only — no fetches, '
                 'no writes.',
        )
        parser.add_argument(
            '--employers-only', action='store_true',
            help='Refresh reg_code/about for companies with stale '
                 'detail_fetched_at, via their freshest live '
                 'vacancy.',
        )
        parser.add_argument(
            '--stale-days', type=int, default=7,
            help='--employers-only: companies whose '
                 'detail_fetched_at is null or older than this '
                 'many days are refreshed (default: 7).',
        )

    def handle(self, *args, **options):
        if options['batch_size'] < 1:
            raise CommandError('--batch-size must be >= 1.')
        portal_id = nextjs_portal_id()
        if portal_id is None:
            raise CommandError(
                'No configured portal with type "nextjs" — detail '
                'pages only exist on the public cv.lv portal.'
            )
        scraper = VacancyScrapper(portal_id=portal_id)
        if options['employers_only']:
            self._refresh_companies(scraper, options)
        else:
            self._link_vacancies(scraper, options)

    def _fetch_detail_slice(self, scraper, vacancy):
        """One throttled detail fetch -> employer slice or None."""
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
        detail_slice = company_linking.employer_detail_slice(detail)
        if detail_slice['employer_id'] is None:
            return 'no_employer'
        return detail_slice

    def _link_vacancies(self, scraper, options):
        if options['ids']:
            qs = Vacancy.objects.filter(
                vacancy_portal_id__in=options['ids']
            ).order_by('-last_seen')
        else:
            qs = (
                Vacancy.objects
                .filter(company__isnull=True)
                .order_by('-last_seen')
            )
        if options['limit']:
            qs = qs[:options['limit']]
        total = qs.count()
        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] {total} vacancy(ies) would be '
                f'detail-fetched and linked'
            ))
            return

        counts = {'linked': 0}
        done = 0
        for vacancy in qs.iterator(chunk_size=options['batch_size']):
            result = self._fetch_detail_slice(scraper, vacancy)
            if not isinstance(result, dict):
                counts[result] = counts.get(result, 0) + 1
                logger.info(
                    f"Vacancy {vacancy.vacancy_portal_id}: {result}"
                )
            else:
                now = timezone.now()
                company = company_linking.resolve_company(
                    result['employer_id'],
                    result['employer_name'],
                    now=now,
                )
                company_linking.apply_employer_detail(
                    company, result, now=now
                )
                vacancy.company = company
                vacancy.detail_fetched_at = now
                vacancy.save(
                    update_fields=['company', 'detail_fetched_at']
                )
                counts['linked'] += 1
            done += 1
            if done % options['batch_size'] == 0:
                self.stdout.write(f'  ... processed {done}/{total}')

        message = (
            f'{done} vacancy(ies) processed: '
            + ', '.join(f'{k}={v}' for k, v in sorted(counts.items()))
        )
        logger.info('link_vacancies_to_companies: %s', message)
        self.stdout.write(self.style.SUCCESS(f'done: {message}'))

    def _refresh_companies(self, scraper, options):
        cutoff = timezone.now() - timedelta(
            days=options['stale_days']
        )
        qs = (
            Company.objects
            .filter(merged_into__isnull=True)
            .filter(
                Q(detail_fetched_at__isnull=True)
                | Q(detail_fetched_at__lt=cutoff)
            )
            .order_by(F('detail_fetched_at').asc(nulls_first=True))
        )
        if options['limit']:
            qs = qs[:options['limit']]
        total = qs.count()
        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] {total} company(ies) with stale '
                f'detail_fetched_at would be refreshed'
            ))
            return

        counts = {'refreshed': 0, 'no_live_vacancy': 0,
                  'other_company': 0}
        done = 0
        for company in qs.iterator(chunk_size=options['batch_size']):
            outcome = 'no_live_vacancy'
            for vacancy in company.vacancies.order_by(
                '-last_seen'
            )[:MAX_VACANCY_ATTEMPTS]:
                result = self._fetch_detail_slice(scraper, vacancy)
                if not isinstance(result, dict):
                    continue
                now = timezone.now()
                resolved = company_linking.resolve_company(
                    result['employer_id'],
                    result['employer_name'],
                    now=now,
                )
                company_linking.apply_employer_detail(
                    resolved, result, now=now
                )
                outcome = 'refreshed'
                if resolved.pk != company.pk:
                    outcome = 'other_company'
                    logger.warning(
                        f"Vacancy {vacancy.vacancy_portal_id} of "
                        f"company {company.pk} resolved to a "
                        f"different company {resolved.pk} — "
                        f"refreshed that one instead"
                    )
                break
            counts[outcome] += 1
            done += 1
            if done % options['batch_size'] == 0:
                self.stdout.write(f'  ... processed {done}/{total}')

        message = (
            f'{done} company(ies) processed: '
            + ', '.join(f'{k}={v}' for k, v in sorted(counts.items()))
        )
        logger.info(
            'link_vacancies_to_companies --employers-only: %s',
            message,
        )
        self.stdout.write(self.style.SUCCESS(f'done: {message}'))

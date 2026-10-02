"""Enrich pending/failed/not_found Shows via OMDb (+ AI title
translation and the key-free Cinemeta fallback) without rescraping
(tv_show_normalization_plan.md §5).

Builds a ``TVProgramScraper`` instance purely for its throttled
``make_request`` — run() is never called.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ai_providers import errors as ai_errors
from ai_providers.client import get_job_client
from tv_programs.ai_jobs import TITLE_TRANSLATION
from tv_programs.enrichment import OMDbClient, enrich_show
from tv_programs.models import Show
from tv_programs.scraper import TVProgramScraper

logger = logging.getLogger('tv_programs')

DEFAULT_BATCH_SIZE = 100


class Command(BaseCommand):
    help = (
        'Enrich Show rows (OMDb -> AI translation -> Cinemeta). '
        'Default target: enrichment_status=pending.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--status',
            choices=[c for c, _ in Show.EnrichmentStatus.choices
                     if c != Show.EnrichmentStatus.ENRICHED],
            default=Show.EnrichmentStatus.PENDING,
            help='Which shows to enrich (default: pending).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Max shows to process.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f'Shows fetched per query (default '
                 f'{DEFAULT_BATCH_SIZE}).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print the matching show count without enriching.',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size must be >= 1.')
        status = options['status']
        limit = options['limit']

        qs = (
            Show.objects.filter(enrichment_status=status)
            .order_by('created_at', 'id')
        )
        if limit:
            qs = qs[:limit]
        total = qs.count()
        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] {total} show(s) with status={status} '
                f'would be enriched'
            ))
            return

        # Reuse the scraper's throttled/retrying HTTP; never run it.
        scraper = TVProgramScraper(enrich=False)
        api_key = getattr(settings, 'OMDB_KEY', '') or ''
        omdb = (
            OMDbClient(scraper.make_request, api_key)
            if api_key else None
        )
        if omdb is None:
            self.stdout.write(
                'OMDB_KEY not set — skipping OMDb lookups '
                '(Cinemeta fallback still applies)'
            )
        ai_client = None
        try:
            ai_client = get_job_client(TITLE_TRANSLATION)
        except ai_errors.AIError as e:
            self.stdout.write(
                f'Title translation job unavailable: {e}'
            )

        counts = {'enriched': 0, 'not_found': 0, 'failed': 0}
        done = 0
        for show in qs.iterator(chunk_size=batch_size):
            enrich_show(
                show,
                omdb=omdb,
                ai_client=ai_client,
                request_fn=scraper.make_request,
            )
            counts[show.enrichment_status] = (
                counts.get(show.enrichment_status, 0) + 1
            )
            done += 1
            if done % batch_size == 0:
                self.stdout.write(f'processed {done}/{total}')

        message = (
            f'{done} show(s) processed: '
            + ', '.join(f'{k}={v}' for k, v in sorted(counts.items()))
        )
        logger.info('enrich_tv_shows: %s', message)
        self.stdout.write(self.style.SUCCESS(f'done: {message}'))

import logging
import traceback

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from news.feeds import ensure_seeded
from news.scraper import NewsScraper
from scrape_jobs.runner import (
    ScrapeJobRunner,
    cooldown_skip_reason,
    detect_executed_by,
)

logger = logging.getLogger('news')

JOB_SLUG = 'news.feeds'
# The scrape is scheduled daily, so the GCP fallback cooldown is
# one day — enough to dedup same-day reruns.
GCP_COOLDOWN_DAYS = 1


class Command(BaseCommand):
    help = 'Scrapes enabled news RSS feeds into NewsArticle rows'

    def add_arguments(self, parser):
        parser.add_argument(
            '--cycle',
            type=str,
            default=None,
            help='Resume-cycle key; default today (UTC)',
        )
        parser.add_argument(
            '--fresh',
            action='store_true',
            help="Ignore this cycle's completed items — full pass",
        )
        parser.add_argument(
            '--resume-from',
            type=str,
            default=None,
            dest='resume_from',
            help='Debug: start at the item with this key',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Fetch and parse but write nothing (no articles '
                 'or run rows)',
        )
        parser.add_argument(
            '--ignore-cooldown',
            action='store_true',
            dest='ignore_cooldown',
            help='Run even if a scrape already succeeded in the '
                 'cooldown window (1 day on GCP, current cycle '
                 'locally)',
        )
        parser.add_argument(
            '--source',
            type=str,
            default=None,
            help='Scrape only the source with this slug',
        )

    def handle(self, *args, **options):
        start_time = timezone.now()
        self.stdout.write(f"Starting news scraping at {start_time}")

        # Idempotent — sources/topics exist before the scraper
        # reads them; admin edits are never overwritten.
        ensure_seeded(dry_run=options['dry_run'])

        # --source is a targeted re-scrape: it must not be refused
        # by the cycle gate (a full run may already have succeeded
        # this cycle) and it must not satisfy the gate either — its
        # run is marked PARTIAL below so a later full pass is still
        # allowed to scrape the remaining sources.
        if not (
            options['ignore_cooldown']
            or options['fresh']
            or options['dry_run']
            or options['source']
        ):
            reason = cooldown_skip_reason(
                JOB_SLUG, detect_executed_by(), options['cycle'],
                days=GCP_COOLDOWN_DAYS,
            )
            if reason:
                msg = f'{JOB_SLUG}: skipping — {reason}'
                logger.info(msg)
                self.stdout.write(msg)
                return

        runner = ScrapeJobRunner(
            slug=JOB_SLUG,
            description='News RSS feed scrape (all enabled sources)',
            cycle_key=options['cycle'],
            # A --source run is a targeted re-scrape: fresh=True
            # makes the selected feed eligible again even when it
            # was already DONE this cycle; the other feeds' items
            # are filtered out downstream and stay pending.
            fresh=options['fresh'] or bool(options['source']),
            resume_from=options['resume_from'],
            dry_run=options['dry_run'],
        )

        try:
            scraper = NewsScraper(
                runner=runner,
                dry_run=options['dry_run'],
                source_slug=options['source'],
            )
            scraper.run()
            if options['source']:
                # Only a subset of the job's items was processed —
                # PARTIAL keeps cycle_scrape_exists unsatisfied so
                # the full pass is not gated off.
                runner.mark_partial()
            runner.finish()
            end_time = timezone.now()
            duration = (end_time - start_time).total_seconds()
            self.stdout.write(
                self.style.SUCCESS(
                    f"News scraping finished in "
                    f"{duration:.2f} seconds"
                )
            )

        except Exception as e:
            runner.finish('FAILED', traceback.format_exc())
            self.stdout.write(
                self.style.ERROR("Error running news scraper")
            )
            self.stderr.write(str(e))
            raise CommandError(
                f"Error running news scraper: {str(e)}"
            )

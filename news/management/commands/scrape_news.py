import logging
import traceback
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from news.backfill import NewsBackfillScraper
from news.feeds import ensure_seeded
from news.scraper import NewsScraper
from scrape_jobs.runner import (
    ScrapeJobRunner,
    cooldown_skip_reason,
    detect_executed_by,
)

logger = logging.getLogger('news')

JOB_SLUG = 'news.feeds'
BACKFILL_JOB_SLUG = 'news.backfill'
# Constant cycle key: every --backfill invocation resumes the
# same DONE-key set across days and Cloud Run executions; a
# deliberate re-sweep uses --cycle backfill-YYYY-MM or --fresh.
BACKFILL_CYCLE_KEY = 'backfill'
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
            help="Resume-cycle key; default today (UTC), "
                 "or the constant 'backfill' under --backfill",
        )
        parser.add_argument(
            '--fresh',
            action='store_true',
            help="Ignore this cycle's completed items — full "
                 "pass; also skips conditional-GET headers so "
                 "feeds are re-parsed even when unchanged (to "
                 "force just one feed, clear its "
                 "etag/last_modified in admin instead)",
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
                 'or run rows). Right after a real run a feed '
                 'unchanged since then answers 304 and shows '
                 'nothing — add --fresh to force parsing',
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
            help='Scrape only the source with this slug '
                 '(re-fetches even if the feed is unchanged)',
        )
        parser.add_argument(
            '--backfill',
            action='store_true',
            help='Backfill mode: walk sitemaps/archives for '
                 'historical articles instead of polling RSS '
                 'feeds (job news.backfill, cycle "backfill")',
        )
        parser.add_argument(
            '--since',
            type=str,
            default=None,
            help='Backfill only: process partitions covering '
                 'YYYY-MM-DD or later (the synced item set is '
                 'always the full range)',
        )
        parser.add_argument(
            '--until',
            type=str,
            default=None,
            help='Backfill only: process partitions covering '
                 'YYYY-MM-DD or earlier (default: today; the '
                 'synced item set is always the full range)',
        )
        parser.add_argument(
            '--max-minutes',
            type=int,
            default=None,
            dest='max_minutes',
            help='Backfill only: wall-clock budget — on '
                 'exhaustion the run ends PARTIAL and a '
                 're-invocation resumes the remaining items',
        )

    def handle(self, *args, **options):
        backfill_only = [
            name
            for name in ('since', 'until', 'max_minutes')
            if options[name] is not None
        ]
        if backfill_only and not options['backfill']:
            flags = ', '.join(
                '--' + name.replace('_', '-')
                for name in backfill_only
            )
            raise CommandError(
                f'{flags} only work with --backfill'
            )

        start_time = timezone.now()
        self.stdout.write(f"Starting news scraping at {start_time}")

        # Idempotent — sources/topics exist before the scraper
        # reads them; admin edits are never overwritten.
        ensure_seeded(dry_run=options['dry_run'])

        if options['backfill']:
            # Backfill branches before the cooldown gate — it is
            # always a deliberate manual operation.
            self._handle_backfill(options, start_time)
            return

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

    def _handle_backfill(self, options, start_time):
        """--backfill: sitemap/archive walk under job slug
        'news.backfill', checkpointed per (source, partition)."""
        try:
            since = (
                date.fromisoformat(options['since'])
                if options['since']
                else None
            )
            until = (
                date.fromisoformat(options['until'])
                if options['until']
                else None
            )
        except ValueError as e:
            raise CommandError(
                f'invalid --since/--until date: {e}'
            )
        if since and until and since > until:
            raise CommandError(
                '--since must not be after --until'
            )
        deadline = None
        if options['max_minutes'] is not None:
            deadline = start_time + timedelta(
                minutes=options['max_minutes']
            )

        runner = ScrapeJobRunner(
            slug=BACKFILL_JOB_SLUG,
            description='News sitemap/archive backfill '
                        '(historical articles)',
            cycle_key=options['cycle'] or BACKFILL_CYCLE_KEY,
            # --source is NOT implied-fresh here — a narrowed
            # run still skips partitions DONE this cycle.
            fresh=options['fresh'],
            resume_from=options['resume_from'],
            dry_run=options['dry_run'],
        )

        try:
            scraper = NewsBackfillScraper(
                runner=runner,
                dry_run=options['dry_run'],
                source_slug=options['source'],
                since=since,
                until=until,
                deadline=deadline,
            )
            if options['dry_run']:
                # Listing mode: enumerate partitions and count
                # listing URLs — no article fetches, no writes.
                for line in scraper.partition_listing():
                    self.stdout.write(line)
            else:
                scraper.run()
            if scraper.budget_exhausted or options['source']:
                # Honest unfinished work: the wall-clock budget
                # ran out mid-walk, or --source covered only a
                # subset of the job's items.
                runner.mark_partial()
            runner.finish()
            end_time = timezone.now()
            duration = (end_time - start_time).total_seconds()
            self.stdout.write(
                self.style.SUCCESS(
                    f"News backfill finished in "
                    f"{duration:.2f} seconds"
                )
            )

        except Exception as e:
            runner.finish('FAILED', traceback.format_exc())
            self.stdout.write(
                self.style.ERROR("Error running news backfill")
            )
            self.stderr.write(str(e))
            raise CommandError(
                f"Error running news backfill: {str(e)}"
            )

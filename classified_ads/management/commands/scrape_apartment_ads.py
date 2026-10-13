import logging
import traceback

from django.core.management.base import BaseCommand, CommandError

from classified_ads.apartment_scraper import ApartmentAdScraper
from scrape_jobs.runner import (
    ScrapeJobRunner,
    cooldown_skip_reason,
    detect_executed_by,
)

logger = logging.getLogger('classified_ads')

JOB_SLUG = 'classified_ads.apartment_ads'


class Command(BaseCommand):
    help = 'Scrapes apartment ads from ss.com.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--max-pages',
            type=int,
            default=10,
            help='Max pages to scrape per region per deal type',
        )
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
            help='Fetch and parse but write nothing (no ads, '
                 'sightings, or run rows)',
        )
        parser.add_argument(
            '--ignore-cooldown',
            action='store_true',
            dest='ignore_cooldown',
            help='Run even if a scrape already succeeded in the '
                 'cooldown window (6 days on GCP, current cycle '
                 'locally)',
        )

    def handle(self, *args, **options):
        if not (
            options['ignore_cooldown']
            or options['fresh']
            or options['dry_run']
        ):
            reason = cooldown_skip_reason(
                JOB_SLUG, detect_executed_by(), options['cycle']
            )
            if reason:
                msg = f'{JOB_SLUG}: skipping — {reason}'
                logger.info(msg)
                self.stdout.write(msg)
                return
        runner = ScrapeJobRunner(
            slug=JOB_SLUG,
            description=(
                'Apartment ads scrape (ss.com regions x deal types)'
            ),
            cycle_key=options['cycle'],
            fresh=options['fresh'],
            resume_from=options['resume_from'],
            dry_run=options['dry_run'],
        )
        scraper = ApartmentAdScraper(
            max_pages=options['max_pages'],
            runner=runner,
            dry_run=options['dry_run'],
        )
        try:
            scraper.run()
        except Exception as e:
            runner.finish('FAILED', traceback.format_exc())
            raise CommandError(f'Scraping failed: {e}')
        runner.finish()
        self.stdout.write(
            self.style.SUCCESS(
                'Apartment ads scraping complete.'
            )
        )

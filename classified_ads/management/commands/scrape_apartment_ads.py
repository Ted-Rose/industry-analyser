import traceback

from django.core.management.base import BaseCommand, CommandError

from classified_ads.apartment_scraper import ApartmentAdScraper
from scrape_jobs.runner import ScrapeJobRunner


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

    def handle(self, *args, **options):
        runner = ScrapeJobRunner(
            slug='classified_ads.apartment_ads',
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

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
import logging
import traceback

from scrape_jobs.runner import ScrapeJobRunner
from tv_programs.scraper import TVProgramScraper

# Use the app name as the logger name to match settings configuration
logger = logging.getLogger('tv_programs')


class Command(BaseCommand):
    help = 'Runs the TV program scraper to fetch and store TV program data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force scraping even if recent data exists',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Dry run mode - will not save to database',
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
            dest='resume_from',
            type=str,
            default=None,
            help='Debug: start at the item with this key',
        )
        parser.add_argument(
            '--days-past',
            type=int,
            default=None,
            help='Days back to scrape (default: 7)',
        )
        parser.add_argument(
            '--days-future',
            type=int,
            default=None,
            help='Days ahead to scrape (default: 7)',
        )
        parser.add_argument(
            '--no-enrich',
            action='store_true',
            help='Skip OMDb/AI enrichment of new Shows',
        )

    def handle(self, *args, **options):
        start_time = timezone.now()
        self.stdout.write(f"Starting TV program scraping at {start_time}")

        force = options.get('force', False)
        if force:
            self.stdout.write(
                "Force mode enabled - will scrape regardless of "
                "existing data"
            )

        runner = ScrapeJobRunner(
            slug='tv_programs.guide',
            description='TV guide scrape (tet.lv channels x dates)',
            cycle_key=options['cycle'],
            # --force ("ignore recent data") maps onto a fresh pass.
            fresh=options['fresh'] or options['force'],
            resume_from=options['resume_from'],
            dry_run=options['dry_run'],
        )

        config = {}
        if options['days_past'] is not None:
            config['days_in_past'] = options['days_past']
        if options['days_future'] is not None:
            config['days_in_future'] = options['days_future']

        try:
            scraper = TVProgramScraper(
                config=config or None,
                runner=runner,
                dry_run=options['dry_run'],
                enrich=not options['no_enrich'],
            )
            programs = scraper.run()
            runner.finish()
            end_time = timezone.now()
            duration = (end_time - start_time).total_seconds()

            if programs:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully scraped {len(programs)} TV programs in "
                        f"{duration:.2f} seconds"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"No TV programs were scraped. Completed in "
                        f"{duration:.2f} seconds"
                    )
                )

        except Exception as e:
            runner.finish('FAILED', traceback.format_exc())
            self.stdout.write(
                self.style.ERROR("Error running TV program scraper")
            )
            self.stderr.write(str(e))
            raise CommandError(
                f"Error running TV program scraper: {str(e)}"
            )

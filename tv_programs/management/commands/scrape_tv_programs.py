from django.core.management.base import BaseCommand
from django.utils import timezone
import logging

from tv_programs.scraper import TVProgramScraper

logger = logging.getLogger(__name__)


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

    def handle(self, *args, **options):
        start_time = timezone.now()
        self.stdout.write(f"Starting TV program scraping at {start_time}")

        force = options.get('force', False)
        if force:
            self.stdout.write("Force mode enabled - will scrape regardless of existing data")
            
        try:
            scraper = TVProgramScraper()
            programs = scraper.run()
            end_time = timezone.now()
            duration = (end_time - start_time).total_seconds()

            if programs:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Successfully scraped {len(programs)} TV programs in {duration:.2f} seconds"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"No TV programs were scraped. Completed in {duration:.2f} seconds"
                    )
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error running TV program scraper"))
            self.stderr.write(str(e))
            raise CommandError(f"Error running TV program scraper: {str(e)}")

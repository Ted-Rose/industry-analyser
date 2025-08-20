from django.core.management.base import BaseCommand
from django.utils import timezone
import logging

from tv_programs.scraper import TVProgramScraper

logger = logging.getLogger(__name__)


class ScrapeTVProgramsCommand(BaseCommand):
    help = 'Runs the TV program scraper to fetch and store TV program data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force scraping even if recent data exists',
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
            duration = end_time - start_time

            if programs:
                msg = (
                    f"Successfully scraped {len(programs)} TV programs "
                    f"in {duration.total_seconds():.2f} seconds"
                )
                self.stdout.write(self.style.SUCCESS(msg))
            else:
                msg = (
                    f"No TV programs were scraped. "
                    f"Completed in {duration.total_seconds():.2f} seconds"
                )
                self.stdout.write(self.style.WARNING(msg))

        except Exception as e:
            logger.exception("Error running TV program scraper")
            self.stdout.write(
                self.style.ERROR(f"Error running TV program scraper: {str(e)}")
            )

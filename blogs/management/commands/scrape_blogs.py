from django.core.management.base import BaseCommand
from blogs.scraper import BlogScraper
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    """
    Django management command to scrape blog posts.
    """
    help = 'Scrapes blog posts from the configured source.'

    def handle(self, *args, **options):
        """
        The main logic for the command.
        """
        self.stdout.write(self.style.SUCCESS('Starting the blog scraper...'))
        
        try:
            # First, let's make sure PyYAML is installed.
            import yaml
        except ImportError:
            self.stderr.write(self.style.ERROR(
                "PyYAML is not installed. Please install it by running: "
                "pip install -r requirements.txt"
            ))
            return

        try:
            scraper = BlogScraper()
            scraper.run()
            self.stdout.write(self.style.SUCCESS('Blog scraper finished successfully.'))
        except Exception as e:
            logger.error(f"An error occurred during scraping: {e}", exc_info=True)
            self.stderr.write(self.style.ERROR(f'An error occurred: {e}'))

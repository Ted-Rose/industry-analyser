from django.core.management.base import BaseCommand
from blogs.scraper import BlogScraper
from blogs.models import Theme
from django.db.models import Q
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Django management command to scrape blog posts.
    """
    help = 'Scrapes blog posts from the configured source.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--theme',
            type=str,
            help='Analyze pages for a specific theme only (by theme name)'
        )
        parser.add_argument(
            '--reanalyze',
            action='store_true',
            help='Re-analyze existing pages for the specified theme (use with --theme)'
        )

    def handle(self, *args, **options):
        """
        The main logic for the command.
        """
        theme_filter = options.get('theme')
        reanalyze = options.get('reanalyze', False)

        if theme_filter:
            self.stdout.write(self.style.SUCCESS(
                f'Starting blog scraper for theme: {theme_filter}...'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                'Starting blog scraper for all themes...'
            ))

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
            # Validate theme if specified
            target_theme = None
            if theme_filter:
                try:
                    target_theme = Theme.objects.get(
                        Q(name=theme_filter)
                    )
                    self.stdout.write(self.style.SUCCESS(
                        f'Found theme: {target_theme.name}'
                    ))
                except Theme.DoesNotExist:
                    self.stderr.write(self.style.ERROR(
                        f'Theme "{theme_filter}" not found in database.'
                    ))
                    return

            scraper = BlogScraper(
                target_theme=target_theme,
                reanalyze=reanalyze
            )
            scraper.run()
            self.stdout.write(self.style.SUCCESS(
                'Blog scraper finished successfully.'
            ))
        except Exception as e:
            logger.error(
                f"An error occurred during scraping: {e}",
                exc_info=True
            )
            self.stderr.write(self.style.ERROR(f'An error occurred: {e}'))

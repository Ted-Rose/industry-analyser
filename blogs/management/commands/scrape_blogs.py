from django.core.management.base import BaseCommand
from blogs.scraper import BlogScraper
from blogs.models import Theme
from django.db.models import Q
import logging
import traceback

from scrape_jobs.runner import ScrapeJobRunner

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
            help='Re-analyze existing pages for the specified theme '
                 '(use with --theme)'
        )
        parser.add_argument(
            '--max-api-requests',
            type=int,
            default=None,
            help=(
                'Cap AI requests sent this run. The effective cap is '
                'the lower of this value and the AIJob row\'s '
                'max_requests_per_run (editable in admin).'
            )
        )
        parser.add_argument(
            '--cycle',
            type=str,
            default=None,
            help='Resume-cycle key; default today (UTC)'
        )
        parser.add_argument(
            '--fresh',
            action='store_true',
            help="Ignore this cycle's completed items — full pass"
        )
        parser.add_argument(
            '--resume-from',
            dest='resume_from',
            type=str,
            default=None,
            help='Debug: start at the item with this key'
        )
        parser.add_argument(
            '--dry-run',
            dest='dry_run',
            action='store_true',
            help='Fetch listings and pages but write nothing and '
                 'make no AI calls'
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

        runner = None
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

            # Built only after theme validation so the early-return
            # path never leaves a dangling RUNNING row.
            runner = ScrapeJobRunner(
                slug='blogs.blog_posts',
                description=(
                    'Blog posts scrape + theme analysis (spoki.lv)'
                ),
                cycle_key=options['cycle'],
                fresh=options['fresh'],
                resume_from=options['resume_from'],
                dry_run=options['dry_run'],
            )
            scraper = BlogScraper(
                target_theme=target_theme,
                reanalyze=reanalyze,
                max_api_requests=options.get('max_api_requests'),
                runner=runner,
                dry_run=options['dry_run'],
            )
            scraper.run()
            runner.finish()
            self.stdout.write(self.style.SUCCESS(
                'Blog scraper finished successfully.'
            ))
        except Exception as e:
            if runner is not None:
                runner.finish('FAILED', traceback.format_exc())
            logger.error(
                f"An error occurred during scraping: {e}",
                exc_info=True
            )
            self.stderr.write(self.style.ERROR(f'An error occurred: {e}'))

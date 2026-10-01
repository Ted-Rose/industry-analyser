import traceback

from django.core.management.base import BaseCommand, CommandError

from fetcher.scraper import VacancyScrapper
from scrape_jobs.runner import ScrapeJobRunner


class Command(BaseCommand):
    help = "Runs the vacancy scraper for a given job portal."

    def add_arguments(self, parser):
        parser.add_argument(
            'portal_id', nargs='?', type=int, default=1
        )
        parser.add_argument(
            '--cycle', type=str, default=None,
            help='Resume-cycle key; default today (UTC)',
        )
        parser.add_argument(
            '--fresh', action='store_true',
            help="Ignore this cycle's completed items — full pass",
        )
        parser.add_argument(
            '--resume-from', dest='resume_from', default=None,
            help='Debug: start at the item with this key',
        )
        parser.add_argument(
            '--dry-run', dest='dry_run', action='store_true',
            help='Fetch and parse but write nothing (no vacancies, '
                 'files, or run rows)',
        )

    def handle(self, *args, **options):
        portal_id = options['portal_id']
        runner = ScrapeJobRunner(
            slug=f'fetcher.vacancies.{portal_id}',
            description=f'Vacancy scrape, portal {portal_id}',
            cycle_key=options['cycle'],
            fresh=options['fresh'],
            resume_from=options['resume_from'],
            dry_run=options['dry_run'],
        )
        try:
            scraper = VacancyScrapper(
                portal_id=portal_id,
                runner=runner,
                dry_run=options['dry_run'],
            )
            scraper.run()
        except Exception as e:
            runner.finish('FAILED', traceback.format_exc())
            error_msg = f"Error running vacancy scraper: {e}"
            self.stdout.write(self.style.ERROR(error_msg))
            raise CommandError(error_msg)
        runner.finish()
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully ran scraper for portal {portal_id}"
            )
        )

import traceback

from django.core.management.base import BaseCommand, CommandError

from fetcher.scraper import VacancyScrapper, load_portals_config
from scrape_jobs.runner import ScrapeJobRunner, iso_week_cycle_key


class Command(BaseCommand):
    help = (
        "Runs the vacancy scraper for all configured portals "
        "(or a single one when portal_id is given)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'portal_id', nargs='?', type=int, default=None,
            help='Scrape only this portal (default: all configured)',
        )
        parser.add_argument(
            '--cycle', type=str, default=None,
            help='Resume-cycle key; default current ISO week (UTC)',
        )
        parser.add_argument(
            '--fresh', action='store_true',
            help="Ignore this cycle's completed items — full pass",
        )
        parser.add_argument(
            '--resume-from', dest='resume_from', default=None,
            help='Debug: start at the item with this key — only '
                 'meaningful together with a portal_id',
        )
        parser.add_argument(
            '--dry-run', dest='dry_run', action='store_true',
            help='Fetch and parse but write nothing (no vacancies, '
                 'files, or run rows)',
        )

    def handle(self, *args, **options):
        portal_id = options['portal_id']
        if portal_id is not None:
            portal_ids = [portal_id]
        else:
            portal_ids = sorted(load_portals_config(), key=int)
        failed = []
        for pid in portal_ids:
            runner = ScrapeJobRunner(
                slug=f'fetcher.vacancies.{pid}',
                description=f'Vacancy scrape, portal {pid}',
                cycle_key=options['cycle'] or iso_week_cycle_key(),
                fresh=options['fresh'],
                resume_from=options['resume_from'],
                dry_run=options['dry_run'],
            )
            try:
                scraper = VacancyScrapper(
                    portal_id=pid,
                    runner=runner,
                    dry_run=options['dry_run'],
                )
                scraper.run()
            except Exception as e:
                runner.finish('FAILED', traceback.format_exc())
                failed.append(pid)
                self.stdout.write(
                    self.style.ERROR(
                        f"Error running vacancy scraper for "
                        f"portal {pid}: {e}"
                    )
                )
                continue
            runner.finish()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully ran scraper for portal {pid}"
                )
            )
        if failed:
            raise CommandError(
                f"Vacancy scrape failed for portal(s): "
                f"{', '.join(map(str, failed))}"
            )

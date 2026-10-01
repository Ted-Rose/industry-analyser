from django.core.management.base import BaseCommand, CommandError

from fetcher.scraper import VacancyScrapper


class Command(BaseCommand):
    help = "Runs the vacancy scraper for a given job portal."

    def add_arguments(self, parser):
        parser.add_argument(
            'portal_id', nargs='?', type=int, default=1
        )

    def handle(self, *args, **options):
        try:
            portal_id = options['portal_id']
            scraper = VacancyScrapper(portal_id=portal_id)
            scraper.run()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully ran scraper for portal {portal_id}"
                )
            )
        except Exception as e:
            error_msg = f"Error running vacancy scraper: {e}"
            self.stdout.write(self.style.ERROR(error_msg))
            raise CommandError(error_msg)
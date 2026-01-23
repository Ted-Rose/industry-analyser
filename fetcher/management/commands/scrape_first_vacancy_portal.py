from django.core.management.base import BaseCommand, CommandError

from fetcher.scraper import VacancyScrapper


class Command(BaseCommand):
    help = "Runs the vacancy scraper for a given job portal."

    def handle(self, *args, **options):
        try:
            portal_id = int(args[0]) if args else 1
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
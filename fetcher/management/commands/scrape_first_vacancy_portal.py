from django.core.management.base import BaseCommand, CommandError
from fetcher.scraper import VacancyScrapper

class Command(BaseCommand):
    help = 'Runs the TV program scraper to fetch and store TV program data'

    def handle(self, *args, **options):
        try:
            portal_id = int(args[0]) if args else 1
            scraper = VacancyScrapper(portal_id=portal_id)
            programs = scraper.run()
            self.stdout.write(self.style.SUCCESS("Successfully scraped TV programs"))
        except Exception as e:
            self.stdout.write(self.style.ERROR("Error running TV program scraper"))
            raise CommandError(f"Error running TV program scraper: {str(e)}")
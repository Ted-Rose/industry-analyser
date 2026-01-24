from django.core.management.base import BaseCommand
from tv_programs.scraper import fetch_tv_program_details

class Command(BaseCommand):
    help = 'Scrapes TV programs from various sources.'

    def handle(self, *args, **options):
        self.stdout.write("Starting TV program scraping...")
        try:
            fetch_tv_program_details()
            self.stdout.write(self.style.SUCCESS('Successfully scraped TV programs.'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'An error occurred during scraping: {e}'))

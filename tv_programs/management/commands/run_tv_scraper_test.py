from django.core.management.base import BaseCommand
from tv_programs.scraper import TVProgramScraper

class Command(BaseCommand):
    help = 'Runs the TV program scraper for a limited integration test.'

    def handle(self, *args, **options):
        self.stdout.write(
            "Starting limited integration test for TV Program Scraper..."
        )

        # Configuration for a small run: 1 day in the past, 0 in the future.
        test_config = {
            'days_in_past': 1,
            'days_in_future': 0,
        }

        scraper = TVProgramScraper(config=test_config)
        
        # Limit to one channel for the test run.
        scraper.channels = {
            "filmzone_hd": "filmzone_hd",
        }

        try:
            scraper.run()
            self.stdout.write(
                self.style.SUCCESS('Integration test completed successfully.')
            )
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f'An error occurred during the test: {e}')
            )

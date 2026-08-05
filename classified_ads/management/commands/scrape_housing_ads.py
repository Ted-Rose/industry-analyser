from django.core.management.base import BaseCommand, CommandError

from classified_ads.housing_scraper import HousingAdScraper


class Command(BaseCommand):
    help = 'Scrapes housing ads from ss.com.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--max-pages',
            type=int,
            default=10,
            help='Max pages to scrape per region per deal type',
        )

    def handle(self, *args, **options):
        try:
            scraper = HousingAdScraper(
                max_pages=options['max_pages'],
            )
            scraper.run()
            self.stdout.write(
                self.style.SUCCESS(
                    'Housing ads scraping complete.'
                )
            )
        except Exception as e:
            raise CommandError(f'Scraping failed: {e}')

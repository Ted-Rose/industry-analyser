from django.core.management.base import BaseCommand, CommandError

from classified_ads.scraper import SsComScraper


class Command(BaseCommand):
    help = 'Scrapes classified real estate ads from ss.com.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--url',
            default=None,
            help='Category URL to scrape (default: Riga flats)',
        )
        parser.add_argument(
            '--max-pages',
            type=int,
            default=10,
            help='Max pages to scrape per district per deal type',
        )

    def handle(self, *args, **options):
        try:
            scraper = SsComScraper(
                initial_url=options['url'],
                max_pages=options['max_pages'],
            )
            scraper.run()
            self.stdout.write(
                self.style.SUCCESS(
                    'Classified ads scraping complete.'
                )
            )
        except Exception as e:
            raise CommandError(f'Scraping failed: {e}')

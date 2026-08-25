from core_scraper.management.commands.base_refetch import (
    BaseRefetchCommand
)
from classified_ads.apartment_scraper import ApartmentAdScraper
from classified_ads.models import ApartmentForRent, ApartmentForSale


class Command(BaseRefetchCommand):
    help = (
        'Refetch and update existing apartment ads from ss.com. '
        'Useful for updating missing or incorrect data like post_date, '
        'house_type, facilities, etc.'
    )

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--deal-type',
            type=str,
            choices=['rent', 'sale'],
            help='Limit refetch to rent or sale ads only',
        )

    def get_model(self):
        deal_type = self.options.get('deal_type')
        if deal_type == 'rent':
            return ApartmentForRent
        elif deal_type == 'sale':
            return ApartmentForSale
        return ApartmentForRent

    def get_scraper_class(self):
        return ApartmentAdScraper

    def get_default_update_fields(self):
        return [
            'post_date',
            'house_type',
            'facilities',
            'comment',
            'seller',
        ]

    def handle(self, *args, **options):
        self.options = options
        deal_type = options.get('deal_type')

        if deal_type:
            self.stdout.write(
                f"Processing {deal_type.upper()} ads only\n"
            )
            super().handle(*args, **options)
        else:
            self.stdout.write("Processing RENT ads...\n")
            options['deal_type'] = 'rent'
            super().handle(*args, **options)

            self.stdout.write("\nProcessing SALE ads...\n")
            options['deal_type'] = 'sale'
            super().handle(*args, **options)

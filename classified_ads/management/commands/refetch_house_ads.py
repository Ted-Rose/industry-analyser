from core_scraper.management.commands.base_refetch import (
    BaseRefetchCommand
)
from classified_ads.housing_scraper import HousingAdScraper
from classified_ads.models import HouseForRent, HouseForSale


# Usage examples:
# Backfill the ~6k rows whose detail-only fields were never
# populated (post_date backfill, rooms hardcoded 0 pre-F8):
# python manage.py refetch_house_ads \
#     --filter post_date__isnull=True
#
# Debug command (refetch specific ad IDs):
# python manage.py refetch_house_ads \
#     --ids PUT_YOUR_AD_IDS_HERE \
#     --deal-type rent
#
# Debug command (custom filter with specific fields):
# python manage.py refetch_house_ads \
#     --filter rooms=0 \
#     --fields rooms,house_type \
#     --deal-type sale \
#     --limit 20 \
#     --dry-run


class Command(BaseRefetchCommand):
    help = (
        'Refetch and update existing house ads from ss.com. '
        'Useful for backfilling detail-only fields like post_date, '
        'rooms, house_type, land_area_sqm, etc.'
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
            return HouseForRent
        elif deal_type == 'sale':
            return HouseForSale
        return HouseForRent

    def get_scraper_class(self):
        return HousingAdScraper

    def get_default_update_fields(self):
        return [
            'post_date',
            'seller',
            'floors',
            'land_area_sqm',
            'comment',
            'rooms',
            'house_type',
            'street_name',
            'street_no',
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

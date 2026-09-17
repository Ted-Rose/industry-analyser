"""
Script to fix incorrectly parsed apartment addresses.

This script re-parses addresses for records where the street_name
ends with a digit, which indicates the house number was incorrectly
included in the street name.
"""
import django
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'industry_analyser.settings')
django.setup()

from classified_ads.models import (  # noqa: E402
    ApartmentForRent, ApartmentForSale
)
from classified_ads.apartment_scraper import ApartmentAdScraper  # noqa: E402


def fix_addresses():
    scraper = ApartmentAdScraper()

    # Find ads where street_name ends with a digit (e.g., "Aldaunes 2")
    # but EXCLUDE:
    # 1. Ads where street_name is ONLY digits (e.g., "5")
    # 2. Ads with korpus notation (e.g., "Ilukstes 54 k-3")
    # 3. Ads with concatenated street+number (e.g., "Virsu48")
    # Those need to be refetched from source
    rent_ads = ApartmentForRent.all_objects.filter(
        street_name__regex=r'.*\d+$'
    ).exclude(
        street_name__regex=r'^\d+$'
    ).exclude(
        street_name__contains=' k-'
    ).exclude(
        street_name__regex=r'[a-zA-Z]\d+$'
    )

    print(f"Found {rent_ads.count()} rent ads to fix")

    # Count records that need refetching (pure numbers)
    needs_refetch_numbers = ApartmentForRent.all_objects.filter(
        street_name__regex=r'^\d+$'
    )
    if needs_refetch_numbers.exists():
        print(f"\nWARNING: {needs_refetch_numbers.count()} rent ads "
              f"have street_name as pure numbers (e.g., '5')")
        print("Refetch command: python manage.py refetch_apartment_ads "
              "--filter 'street_name__regex=^\\d+$' --deal-type rent")
        example_ids = list(
            needs_refetch_numbers.values_list('id', flat=True)[:5]
        )
        print(f"Example IDs: {example_ids}")

    # Count records with korpus notation
    needs_refetch_korpus = ApartmentForRent.all_objects.filter(
        street_name__contains=' k-'
    )
    if needs_refetch_korpus.exists():
        print(f"\nWARNING: {needs_refetch_korpus.count()} rent ads "
              f"have korpus notation (e.g., 'Ilukstes 54 k-3')")
        print("Refetch command: python manage.py refetch_apartment_ads "
              "--filter 'street_name__contains= k-' --deal-type rent")
        example_ids = list(
            needs_refetch_korpus.values_list('id', flat=True)[:5]
        )
        print(f"Example IDs: {example_ids}")

    # Count records with concatenated street+number
    needs_refetch_concat = ApartmentForRent.all_objects.filter(
        street_name__regex=r'[a-zA-Z]\d+$'
    ).exclude(
        street_name__iregex=r'k\d+$'
    )
    if needs_refetch_concat.exists():
        print(f"\nWARNING: {needs_refetch_concat.count()} rent ads "
              f"have concatenated street+number (e.g., 'Virsu48')")
        print("Refetch command: python manage.py refetch_apartment_ads "
              "--filter 'street_name__regex=[a-zA-Z]\\d+$' "
              "--deal-type rent")
        example_ids = list(
            needs_refetch_concat.values_list('id', flat=True)[:5]
        )
        print(f"Example IDs: {example_ids}")

    if (needs_refetch_numbers.exists() or needs_refetch_korpus.exists() or
            needs_refetch_concat.exists()):
        print()

    fixed_count = 0
    for ad in rent_ads:
        original = f"{ad.street_name} {ad.street_no}".strip()

        street_name, street_no, apartment_no = (
            scraper._split_street(original)
        )

        if (street_name != ad.street_name or
                street_no != ad.street_no or
                apartment_no != ad.apartment_no):

            print(f"ID {ad.id}: '{ad.street_name}' + '{ad.street_no}' -> "
                  f"'{street_name}' + '{street_no}' + '{apartment_no}'")

            ad.street_name = street_name
            ad.street_no = street_no
            ad.apartment_no = apartment_no
            ad.save(
                update_fields=['street_name', 'street_no', 'apartment_no']
            )
            fixed_count += 1

    print(f"\nFixed {fixed_count} rent ads")

    # Same logic for sale ads
    sale_ads = ApartmentForSale.all_objects.filter(
        street_name__regex=r'.*\d+$'
    ).exclude(
        street_name__regex=r'^\d+$'
    ).exclude(
        street_name__contains=' k-'
    ).exclude(
        street_name__regex=r'[a-zA-Z]\d+$'
    )

    print(f"\nFound {sale_ads.count()} sale ads to fix")

    # Count sale ads that need refetching (pure numbers)
    needs_refetch_sale_numbers = ApartmentForSale.all_objects.filter(
        street_name__regex=r'^\d+$'
    )
    if needs_refetch_sale_numbers.exists():
        print(f"\nWARNING: {needs_refetch_sale_numbers.count()} "
              f"sale ads have street_name as pure numbers")
        print("Refetch command: python manage.py refetch_apartment_ads "
              "--filter 'street_name__regex=^\\d+$' --deal-type sale")
        example_ids = list(
            needs_refetch_sale_numbers.values_list('id', flat=True)[:5]
        )
        print(f"Example IDs: {example_ids}")

    # Count sale ads with korpus notation
    needs_refetch_sale_korpus = ApartmentForSale.all_objects.filter(
        street_name__contains=' k-'
    )
    if needs_refetch_sale_korpus.exists():
        print(f"\nWARNING: {needs_refetch_sale_korpus.count()} "
              f"sale ads have korpus notation")
        print("Refetch command: python manage.py refetch_apartment_ads "
              "--filter 'street_name__contains= k-' --deal-type sale")
        example_ids = list(
            needs_refetch_sale_korpus.values_list('id', flat=True)[:5]
        )
        print(f"Example IDs: {example_ids}")

    # Count sale ads with concatenated street+number
    needs_refetch_sale_concat = ApartmentForSale.all_objects.filter(
        street_name__regex=r'[a-zA-Z]\d+$'
    ).exclude(
        street_name__iregex=r'k\d+$'
    )
    if needs_refetch_sale_concat.exists():
        print(f"\nWARNING: {needs_refetch_sale_concat.count()} "
              f"sale ads have concatenated street+number")
        print("Refetch command: python manage.py refetch_apartment_ads "
              "--filter 'street_name__regex=[a-zA-Z]\\d+$' "
              "--deal-type sale")
        example_ids = list(
            needs_refetch_sale_concat.values_list('id', flat=True)[:5]
        )
        print(f"Example IDs: {example_ids}")

    if (needs_refetch_sale_numbers.exists() or
            needs_refetch_sale_korpus.exists() or
            needs_refetch_sale_concat.exists()):
        print()

    fixed_count = 0
    for ad in sale_ads:
        original = f"{ad.street_name} {ad.street_no}".strip()
        street_name, street_no, apartment_no = (
            scraper._split_street(original)
        )

        if (street_name != ad.street_name or
                street_no != ad.street_no or
                apartment_no != ad.apartment_no):

            print(f"ID {ad.id}: '{ad.street_name}' + '{ad.street_no}' -> "
                  f"'{street_name}' + '{street_no}' + '{apartment_no}'")

            ad.street_name = street_name
            ad.street_no = street_no
            ad.apartment_no = apartment_no
            ad.save(
                update_fields=['street_name', 'street_no', 'apartment_no']
            )
            fixed_count += 1

    print(f"\nFixed {fixed_count} sale ads")


if __name__ == '__main__':
    fix_addresses()

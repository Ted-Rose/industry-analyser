"""
Management command to validate that no duplicate sightings exist.

Usage:
    python manage.py validate_sightings
    python manage.py validate_sightings --verbose
"""

from django.core.management.base import BaseCommand
from django.db.models import Count
from classified_ads.models import (
    ApartmentForRentSighting,
    ApartmentForSaleSighting,
)


class Command(BaseCommand):
    help = 'Validate that no duplicate sightings exist for the same date'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed information about duplicates if found',
        )

    def handle(self, *args, **options):
        verbose = options['verbose']

        self.stdout.write('=' * 70)
        self.stdout.write('Validating Apartment Sightings for Duplicates')
        self.stdout.write('=' * 70)

        # Check rent sightings
        rent_total = ApartmentForRentSighting.objects.count()
        rent_duplicates = (
            ApartmentForRentSighting.objects
            .values('ad_id', 'seen_on')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )

        self.stdout.write(f'\nRent Sightings:')
        self.stdout.write(f'  Total records: {rent_total:,}')
        self.stdout.write(
            f'  Duplicate groups: {rent_duplicates.count():,}'
        )

        if rent_duplicates.exists():
            self.stdout.write(
                self.style.ERROR('  ✗ DUPLICATES FOUND!')
            )
            if verbose:
                self.stdout.write('\n  Sample duplicates:')
                for dup in rent_duplicates[:10]:
                    self.stdout.write(
                        f"    {dup['ad_id'][:50]}... | "
                        f"{dup['seen_on']} | count: {dup['count']}"
                    )
        else:
            self.stdout.write(
                self.style.SUCCESS('  ✓ No duplicates')
            )

        # Check sale sightings
        sale_total = ApartmentForSaleSighting.objects.count()
        sale_duplicates = (
            ApartmentForSaleSighting.objects
            .values('ad_id', 'seen_on')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )

        self.stdout.write(f'\nSale Sightings:')
        self.stdout.write(f'  Total records: {sale_total:,}')
        self.stdout.write(
            f'  Duplicate groups: {sale_duplicates.count():,}'
        )

        if sale_duplicates.exists():
            self.stdout.write(
                self.style.ERROR('  ✗ DUPLICATES FOUND!')
            )
            if verbose:
                self.stdout.write('\n  Sample duplicates:')
                for dup in sale_duplicates[:10]:
                    self.stdout.write(
                        f"    {dup['ad_id'][:50]}... | "
                        f"{dup['seen_on']} | count: {dup['count']}"
                    )
        else:
            self.stdout.write(
                self.style.SUCCESS('  ✓ No duplicates')
            )

        # Summary
        self.stdout.write('\n' + '=' * 70)
        total_records = rent_total + sale_total
        total_duplicates = (
            rent_duplicates.count() + sale_duplicates.count()
        )

        if total_duplicates == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'✓ VALIDATION PASSED: {total_records:,} '
                    f'records checked, 0 duplicates found'
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    f'✗ VALIDATION FAILED: {total_duplicates:,} '
                    f'duplicate groups found'
                )
            )
            self.stdout.write(
                '\nRecommendation: Check the _write_sightings() '
                'method in apartment_scraper.py'
            )

        self.stdout.write('=' * 70)

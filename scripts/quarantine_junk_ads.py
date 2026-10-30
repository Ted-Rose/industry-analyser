"""
One-time data fix: quarantine junk classified-ad rows (is_hidden).

Background: the 2026-10-29 prod audit (item F2) found ~260
visible rows that are not real housing ads — sheds/garages/land
scraps listed with a token floor area, zero or absurd
price-per-m² values, impossible floors, and two apartment-rent
price outliers. They distort per-region rent-vs-buy stats. Rows
are flagged is_hidden (reversible — un-hide to revert); nothing
is deleted.

Criteria, applied to all_objects rows that are NOT already hidden:

- size <= 5 m² on all four ad tables;
- price_per_sqm == 0 on all four ad tables;
- ApartmentForSale.price_per_sqm < 10 (garages/land listed as
  flats);
- HouseForSale.price_per_sqm > 20000;
- floor > max_floor on the two apartment tables, only where
  max_floor > 0 — the scraper stores 0 when the floor cell is
  unparseable, and 0 is a sentinel for "unknown", not a real
  building height;
- two named ApartmentForRent monthly-price outliers (see
  NAMED_JUNK_AD_IDS).

`last_seen` is preserved via F() — is_hidden is the only field
that changes. Sightings and property links are untouched. New
junk is stopped at ingest by HousingAdScraper's guards; this
script cleans the historic residue.

Run against prod manually — always inspect --dry-run output
first:

    python scripts/quarantine_junk_ads.py --dry-run
    python scripts/quarantine_junk_ads.py
"""
import argparse
import logging
import os
import sys
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE', 'industry_analyser.settings'
)
django.setup()

from django.db import transaction  # noqa: E402
from django.db.models import F, Q  # noqa: E402
from classified_ads.models import (  # noqa: E402
    ApartmentForRent, ApartmentForSale, BaseApartmentAd,
    HouseForRent, HouseForSale,
)

logger = logging.getLogger('classified_ads')

TABLES = [
    ApartmentForRent,
    ApartmentForSale,
    HouseForRent,
    HouseForSale,
]

# ApartmentForRent rows with absurd monthly prices (EUR 9,900 and
# EUR 11,400 per month in the 2026-10-29 audit) — sale-scale or
# mistyped totals posted in the rent section that slipped past
# the is_sale_misclassified heuristic. No docs/code precedent
# exists for a generic monthly_price ceiling, so these stay an
# explicit list rather than a threshold.
NAMED_JUNK_AD_IDS = ('tr_58051263', 'tr_57688885')


def criteria_for(ad_model):
    """Return [(label, Q)] junk-row filters for one ad table."""
    crits = [
        ('size<=5', Q(size__lte=5)),
        ('price_per_sqm=0', Q(price_per_sqm=0)),
    ]
    if ad_model is ApartmentForSale:
        crits.append((
            'price_per_sqm<10', Q(price_per_sqm__lt=10),
        ))
    if ad_model is HouseForSale:
        crits.append((
            'price_per_sqm>20000', Q(price_per_sqm__gt=20000),
        ))
    if issubclass(ad_model, BaseApartmentAd):
        crits.append((
            'floor>max_floor (max_floor>0)',
            Q(floor__gt=F('max_floor')) & Q(max_floor__gt=0),
        ))
    if ad_model is ApartmentForRent:
        crits.append((
            'named AptRent outliers',
            Q(ad_id__in=NAMED_JUNK_AD_IDS),
        ))
    return crits


def collect_matches(ad_model):
    """Return {label: [(pk, ad_id), ...]} per criterion."""
    found = {}
    for label, q in criteria_for(ad_model):
        rows = list(
            ad_model.all_objects.filter(q, is_hidden=False)
            .order_by('pk')
            .values_list('pk', 'ad_id')
        )
        if rows:
            found[label] = rows
    return found


def report_table(ad_model, found):
    """Print the per-criterion pk audit; return pks to hide."""
    pks = {pk for rows in found.values() for pk, _ in rows}
    print(f"\n=== {ad_model._meta.db_table} ===")
    if not found:
        print('  no junk rows matched')
        return pks
    for label, rows in found.items():
        ids = ', '.join(
            f'pk={pk} ({ad_id})' for pk, ad_id in rows
        )
        print(f'  {label}: {len(rows)} row(s)\n    {ids}')
    print(f'  newly hidden (union across criteria): {len(pks)}')
    return pks


def apply_hides(ad_model, pks):
    """Set is_hidden=True on the matched visible rows."""
    if not pks:
        return 0
    with transaction.atomic():
        updated = ad_model.all_objects.filter(
            pk__in=pks, is_hidden=False
        ).update(is_hidden=True, last_seen=F('last_seen'))
    logger.info(
        '%s: quarantined %d junk row(s)',
        ad_model._meta.db_table, updated,
    )
    return updated


def main():
    parser = argparse.ArgumentParser(
        description='Quarantine junk classified-ad rows by '
                    'setting is_hidden=True.'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Report what would change without writing anything',
    )
    args = parser.parse_args()

    if args.dry_run:
        print('DRY RUN — no changes will be written')

    grand = 0
    for ad_model in TABLES:
        found = collect_matches(ad_model)
        pks = report_table(ad_model, found)
        if not args.dry_run:
            grand += apply_hides(ad_model, pks)

    if args.dry_run:
        print('\nDry run finished — re-run without --dry-run to '
              'apply.')
    else:
        print(f'\nDone. Total rows newly hidden: {grand:,}')


if __name__ == '__main__':
    main()

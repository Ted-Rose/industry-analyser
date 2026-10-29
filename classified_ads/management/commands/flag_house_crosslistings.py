"""
Flag HouseForRent rows that are actually for-sale listings.

Two signals, same as the ingest-time check in HousingAdScraper:

1. Cross-deal twin: the ad_id also exists in HouseForSale
   (ss.com "sell or rent" dual listings share one tr_ id; ~1673
   ids on prod as of 2026-10-29 — see
   docs/plans/classified_ads_data_quality_implementation_plan.md).
2. Heuristic: sale-scale monthly_price_per_sqm or Latvian/Russian
   sale keywords in the comment (sale_flags.is_sale_misclassified).

Flagging is additive and reversible: rows are never un-flagged —
clear the flag via the admin (list_editable) if a row was flagged
in error.

Usage:
    python manage.py flag_house_crosslistings --dry-run
    python manage.py flag_house_crosslistings
    python manage.py flag_house_crosslistings --batch-size 500
"""
import logging

from django.core.management.base import BaseCommand

from classified_ads.models import HouseForRent, HouseForSale
from classified_ads.sale_flags import is_sale_misclassified

logger = logging.getLogger('classified_ads')


class Command(BaseCommand):
    help = (
        'Flag HouseForRent rows as is_sale_misclassified when the '
        'same ad_id exists in HouseForSale or the sale heuristic '
        'hits'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be flagged without writing',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Rows fetched/written per batch (default: 500)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        batch_size = options['batch_size']
        mode = 'DRY-RUN (nothing written)' if dry_run else 'WRITE'

        sale_ad_ids = set(
            HouseForSale.all_objects.values_list('ad_id', flat=True)
        )
        self.stdout.write(
            f'HouseForSale ad_ids loaded: {len(sale_ad_ids):,}'
        )

        counts = {
            'scanned': 0,
            'twin': 0,
            'heuristic': 0,
            'flagged': 0,
            'already_flagged': 0,
        }
        to_flag = []

        def flush():
            if not to_flag:
                return
            HouseForRent.all_objects.bulk_update(
                to_flag, ['is_sale_misclassified']
            )
            to_flag.clear()

        qs = HouseForRent.all_objects.order_by('id')
        for ad in qs.iterator(chunk_size=batch_size):
            counts['scanned'] += 1
            if ad.is_sale_misclassified:
                counts['already_flagged'] += 1
                continue
            twin = ad.ad_id in sale_ad_ids
            heuristic = is_sale_misclassified(
                ad.comment, ad.monthly_price_per_sqm
            )
            if not (twin or heuristic):
                continue
            if twin:
                counts['twin'] += 1
            if heuristic:
                counts['heuristic'] += 1
            counts['flagged'] += 1
            if not dry_run:
                ad.is_sale_misclassified = True
                to_flag.append(ad)
                if len(to_flag) >= batch_size:
                    flush()
        if not dry_run:
            flush()

        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(f'flag_house_crosslistings — {mode}')
        self.stdout.write(f'{"=" * 60}')
        self.stdout.write(f'  Rows scanned:          {counts["scanned"]}')
        self.stdout.write(
            f'  Already flagged:       {counts["already_flagged"]}'
        )
        self.stdout.write(
            f'  Cross-deal twin hits:  {counts["twin"]}'
        )
        self.stdout.write(
            f'  Heuristic hits:        {counts["heuristic"]}'
        )
        self.stdout.write(
            f'  Newly flagged (union): {counts["flagged"]}'
        )
        logger.info(
            'flag_house_crosslistings %s: %s', mode, counts,
        )

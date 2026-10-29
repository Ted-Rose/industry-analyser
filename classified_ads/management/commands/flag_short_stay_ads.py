"""
Backfill rate_period / is_room_share on existing rent ads.

New rows get both flags at ingest (the raw price-cell text still
carries '/day', '/dienā', '/week', '/nedēļā' markers there). For
rows that predate the flags the price text is gone, so best-effort
post-hoc detectors run instead (classified_ads/rent_flags.py):

- Apartments: comment short-stay vocabulary, then the two-cell
  consistency ratio — monthly_price/(ppsqm*size) is ~1 for real
  monthly ads but ~30/~4 (or inverse) when exactly one price cell
  was a monthlyized daily/weekly rate. Consistent-ratio short
  stays (both cells /day — ~54 rows at >=€25/m² per the review)
  can only be caught by comment wording.
- Houses: monthly_price_per_sqm is derived (price/size), so the
  ratio trick is impossible — comment vocabulary plus an
  implausibly high stored per-m² rent (>15 €/m²) is the residue
  of a x30 daily rate.
- is_room_share: comment room-share / part-of-property keywords
  (LV+RU+EN) on both tables.

Only rows with rate_period == '' (unknown) are candidates —
a stored 'day'/'week'/'month' is positive ingest or manual
information and is never overwritten. Generic short-term wording
without a period ('īstermiņa īre', 'sezonai') maps to 'day' —
nightly lets dominate ss.com short stays. is_room_share flagging
is additive; rows are never un-flagged — clear flags via the
admin if a row was flagged in error.

Usage:
    python manage.py flag_short_stay_ads --dry-run
    python manage.py flag_short_stay_ads
    python manage.py flag_short_stay_ads --batch-size 500
"""
import logging

from django.core.management.base import BaseCommand

from classified_ads.models import ApartmentForRent, HouseForRent
from classified_ads.rent_flags import (
    SHORT_STAY_PERIODS,
    apartment_rate_period_posthoc,
    house_rate_period_posthoc,
    is_room_share,
)

logger = logging.getLogger('classified_ads')


class Command(BaseCommand):
    help = (
        'Backfill rate_period (day/week) and is_room_share on '
        'ApartmentForRent and HouseForRent rows'
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

        self.stdout.write(f'flag_short_stay_ads — {mode}')
        for label, model, period_fn in (
            (
                'ApartmentForRent',
                ApartmentForRent,
                lambda ad: apartment_rate_period_posthoc(
                    ad.monthly_price,
                    ad.monthly_price_per_sqm,
                    ad.size,
                    ad.comment,
                ),
            ),
            (
                'HouseForRent',
                HouseForRent,
                lambda ad: house_rate_period_posthoc(
                    ad.monthly_price_per_sqm,
                    ad.comment,
                ),
            ),
        ):
            counts = self._flag_table(
                model, period_fn, dry_run, batch_size
            )
            self.stdout.write(f'\n{label}:')
            self.stdout.write(
                f'  Rows scanned:              {counts["scanned"]}'
            )
            self.stdout.write(
                f'  rate_period already set:   '
                f'{counts["period_known"]}'
            )
            self.stdout.write(
                f'  rate_period day/week found:'
                f' {counts["period_flagged"]}'
            )
            self.stdout.write(
                f'  is_room_share already set: '
                f'{counts["room_known"]}'
            )
            self.stdout.write(
                f'  is_room_share flagged:     '
                f'{counts["room_flagged"]}'
            )
            logger.info('flag_short_stay_ads %s %s: %s',
                        mode, label, counts)

    def _flag_table(self, model, period_fn, dry_run, batch_size):
        counts = {
            'scanned': 0,
            'period_known': 0,
            'period_flagged': 0,
            'room_known': 0,
            'room_flagged': 0,
        }
        to_update = []

        def flush():
            if not to_update:
                return
            model.all_objects.bulk_update(
                to_update, ['rate_period', 'is_room_share']
            )
            to_update.clear()

        qs = model.all_objects.order_by('id')
        for ad in qs.iterator(chunk_size=batch_size):
            counts['scanned'] += 1
            dirty = False

            if ad.rate_period:
                counts['period_known'] += 1
            else:
                period = period_fn(ad)
                if period in SHORT_STAY_PERIODS:
                    ad.rate_period = period
                    counts['period_flagged'] += 1
                    dirty = True

            if ad.is_room_share:
                counts['room_known'] += 1
            elif is_room_share(ad.comment):
                ad.is_room_share = True
                counts['room_flagged'] += 1
                dirty = True

            if dirty and not dry_run:
                to_update.append(ad)
                if len(to_update) >= batch_size:
                    flush()

        if not dry_run:
            flush()
        return counts

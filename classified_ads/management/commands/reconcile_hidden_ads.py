"""
Un-hide classified ads that are hidden but still being scraped.

Background: migration 0015 (2026-08-19) hid every ad row with
first_seen < 2026-08-11. Roughly 3,501 of those rows still get
sightings (prod audit 2026-10-29, item F3),
i.e. live listings invisible to every `objects`-based stat.

A hidden row is un-hidden only when ALL of these hold:

- ad_id is a bare real ss.com id ('^tr_\\d+$' — composite and
  malformed ids stay hidden; the F6 work item owns those);
- it has a sighting with seen_on >= today - --days (default 14);
- no sibling row on the same `link` is already visible — a hidden
  bare-id row next to a visible composite-id row is the frozen-
  canonical problem F6 swaps, so both stay untouched here;
- rent models only: is_sale_misclassified=False (a flagged row is
  a sale listing and stays hidden regardless of sightings).

Within an all-hidden link group at most one candidate (lowest pk)
is un-hidden so a duplicate pair never becomes visible together.

Reversible: the pk audit list printed and logged per table lets
ops re-hide exactly the rows this command touched (is_hidden=True
on those pks). `last_seen` is preserved — queryset .update() never
touches auto_now fields, and the explicit F() keeps that obvious.

Usage:
    python manage.py reconcile_hidden_ads --dry-run
    python manage.py reconcile_hidden_ads
    python manage.py reconcile_hidden_ads --days 30 --batch-size 500
    python manage.py reconcile_hidden_ads --model house-sale
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from classified_ads.models import (
    ApartmentForRent,
    ApartmentForSale,
    HouseForRent,
    HouseForSale,
)

logger = logging.getLogger('classified_ads')

# Bare real ss.com row id — composite/malformed ids don't match.
REAL_AD_ID_RE = r'^tr_\d+$'

MODEL_CHOICES = {
    'apartment-rent': ApartmentForRent,
    'apartment-sale': ApartmentForSale,
    'house-rent': HouseForRent,
    'house-sale': HouseForSale,
}


class Command(BaseCommand):
    help = (
        'Un-hide ads (is_hidden=False) that still have recent '
        'sightings and no visible same-link sibling'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be un-hidden without writing',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=14,
            help='Sighting recency window in days (default: 14)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Rows written per UPDATE batch (default: 500)',
        )
        parser.add_argument(
            '--model',
            choices=sorted(MODEL_CHOICES),
            help='Limit to a single ad table (default: all four)',
        )

    def handle(self, *args, **options):
        if options['days'] < 1:
            self.stderr.write('--days must be >= 1')
            return
        dry_run = options['dry_run']
        cutoff = timezone.localdate() - timedelta(
            days=options['days']
        )
        models = (
            [MODEL_CHOICES[options['model']]]
            if options['model'] else list(MODEL_CHOICES.values())
        )

        mode = 'DRY-RUN (nothing written)' if dry_run else 'WRITE'
        self.stdout.write(f'reconcile_hidden_ads — {mode}')
        self.stdout.write(f'Sighting cutoff: seen_on >= {cutoff}')

        grand = 0
        for ad_model in models:
            grand += self._process_table(
                ad_model, cutoff, dry_run, options['batch_size']
            )

        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(f'Total rows un-hidden: {grand:,}')
        if dry_run:
            self.stdout.write(
                'Dry run finished — re-run without --dry-run to apply.'
            )

    def _process_table(self, ad_model, cutoff, dry_run, batch_size):
        """Un-hide qualifying rows in one table; return the count."""
        table = ad_model._meta.db_table
        has_misc_flag = any(
            f.name == 'is_sale_misclassified'
            for f in ad_model._meta.fields
        )
        hidden_qs = ad_model.all_objects.filter(is_hidden=True)
        hidden_total = hidden_qs.count()

        sighted = list(
            hidden_qs
            .filter(
                ad_id__regex=REAL_AD_ID_RE,
                sightings__seen_on__gte=cutoff,
            )
            .annotate(last_sighting=Max('sightings__seen_on'))
            .order_by('pk')
            .iterator()
        )

        candidate_links = {ad.link for ad in sighted}
        # ad_id is unique per table, so a visible row sharing the
        # link is always a *different* ad_id by construction.
        visible_links = set(
            ad_model.all_objects.filter(
                is_hidden=False, link__in=candidate_links,
            ).values_list('link', flat=True)
        )

        counts = {
            'hidden_total': hidden_total,
            'sighted_real_id': len(sighted),
            'skipped_misclassified': 0,
            'skipped_dup_link': 0,
            'unhidden': 0,
        }
        taken_links = set()
        to_unhide = []
        for ad in sighted:
            if has_misc_flag and ad.is_sale_misclassified:
                counts['skipped_misclassified'] += 1
                continue
            if ad.link in visible_links or ad.link in taken_links:
                counts['skipped_dup_link'] += 1
                continue
            taken_links.add(ad.link)
            to_unhide.append(ad)
            if dry_run:
                self.stdout.write(
                    f'  pk={ad.pk} {ad.ad_id} '
                    f'last_sighting={ad.last_sighting} {ad.link}'
                )
        counts['unhidden'] = len(to_unhide)

        if not dry_run and to_unhide:
            pks = [ad.pk for ad in to_unhide]
            with transaction.atomic():
                for i in range(0, len(pks), batch_size):
                    ad_model.all_objects.filter(
                        pk__in=pks[i:i + batch_size],
                        is_hidden=True,
                    ).update(
                        is_hidden=False,
                        last_seen=F('last_seen'),
                    )
            self.stdout.write(
                f'  Un-hidden pks: {",".join(map(str, pks))}'
            )

        self.stdout.write(f'\n=== {table} ===')
        self.stdout.write(f'  Hidden rows:            {hidden_total:,}')
        self.stdout.write(
            f'  Real-id rows sighted in window: '
            f'{counts["sighted_real_id"]:,}'
        )
        self.stdout.write(
            f'  Skipped (sale-misclassified): '
            f'{counts["skipped_misclassified"]:,}'
        )
        self.stdout.write(
            f'  Skipped (same-link visible/dup): '
            f'{counts["skipped_dup_link"]:,}'
        )
        verb = 'Would un-hide' if dry_run else 'Un-hidden'
        self.stdout.write(
            f'  {verb}:               {counts["unhidden"]:,}'
        )
        logger.info(
            'reconcile_hidden_ads %s %s: %s pks=%s',
            'DRY-RUN' if dry_run else 'WRITE', table, counts,
            [ad.pk for ad in to_unhide],
        )
        return counts['unhidden']

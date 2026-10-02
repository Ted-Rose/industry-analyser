"""
Link classified ads to canonical ApartmentProperty/HouseProperty rows.

Usage:
    python manage.py link_ads_to_properties --dry-run
    python manage.py link_ads_to_properties --deal rent --type apartment
    python manage.py link_ads_to_properties --auto-threshold 0.8 \
        --candidate-threshold 0.45 --batch-size 500 --limit 1000
    python manage.py link_ads_to_properties --older-than-days 3

Idempotent: a run only touches ads with match status 'unmatched'
('--relink' also reconsiders 'auto'-linked ads). Oldest ads are
processed first so repost chains accumulate onto one property.
"""
import logging
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Prefetch
from django.utils import timezone

from classified_ads import property_matcher as pm
from classified_ads.models import (
    ApartmentForRent,
    ApartmentForSale,
    ApartmentProperty,
    HouseForRent,
    HouseForSale,
    HouseProperty,
)

logger = logging.getLogger('classified_ads')

MODEL_MAP = {
    ('apartment', 'rent'): (ApartmentForRent, ApartmentProperty),
    ('apartment', 'sale'): (ApartmentForSale, ApartmentProperty),
    ('house', 'rent'): (HouseForRent, HouseProperty),
    ('house', 'sale'): (HouseForSale, HouseProperty),
}

PROP_AD_MODELS = {
    ApartmentProperty: (ApartmentForRent, ApartmentForSale),
    HouseProperty: (HouseForRent, HouseForSale),
}


class Command(BaseCommand):
    help = 'Link classified ads to canonical property rows'

    def add_arguments(self, parser):
        parser.add_argument(
            '--deal',
            choices=['rent', 'sale'],
            help='Limit to a single deal type',
        )
        parser.add_argument(
            '--type',
            dest='property_type',
            choices=['apartment', 'house'],
            help='Limit to a single property type',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Match and report without writing anything',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Ads fetched per query batch (default: 500)',
        )
        parser.add_argument(
            '--auto-threshold',
            type=float,
            default=pm.AUTO_THRESHOLD,
            help='Score at/above which ads auto-link (default: 0.8)',
        )
        parser.add_argument(
            '--candidate-threshold',
            type=float,
            default=pm.CANDIDATE_THRESHOLD,
            help='Score at/above which ads enter review queue '
                 '(default: 0.45)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Max ads to process per table',
        )
        parser.add_argument(
            '--relink',
            action='store_true',
            help='Also reconsider already auto-linked ads',
        )
        parser.add_argument(
            '--older-than-days',
            type=int,
            default=None,
            help='Only process ads whose first_seen is at least '
                 'N days old (default: no age restriction)',
        )

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        self.auto_threshold = options['auto_threshold']
        self.candidate_threshold = options['candidate_threshold']
        self.batch_size = options['batch_size']
        self.relink = options['relink']
        self.older_than_days = options['older_than_days']

        for (ptype, deal), models in MODEL_MAP.items():
            if options['deal'] and options['deal'] != deal:
                continue
            if options['property_type'] and (
                options['property_type'] != ptype
            ):
                continue
            self._process_table(*models, options['limit'])

    def _process_table(self, ad_model, prop_model, limit):
        statuses = ['unmatched']
        if self.relink:
            statuses.append('auto')
        qs = (
            ad_model.all_objects
            .filter(property_match_status__in=statuses)
            .select_related('seller')
            .order_by('first_seen', 'id')
        )
        if self.older_than_days is not None:
            qs = qs.filter(
                first_seen__lte=(
                    timezone.now()
                    - timedelta(days=self.older_than_days)
                )
            )
        if limit:
            qs = qs[:limit]

        counts = defaultdict(int)
        histogram = defaultdict(int)
        blocks = {}

        for ad in qs.iterator(chunk_size=self.batch_size):
            counts['processed'] += 1
            self._link_ad(
                ad, prop_model, blocks, counts, histogram
            )
            if counts['processed'] % self.batch_size == 0:
                self.stdout.write(
                    f'  ... processed {counts["processed"]}'
                )

        self._report(ad_model, counts, histogram)

    def _block_key(self, ad):
        return (
            ad.district.strip().lower(),
            pm.normalize_street_no(ad.street_no),
        )

    def _load_block(self, ad, prop_model):
        """Fetch block candidates and cache their linked ads."""
        rent_model, sale_model = PROP_AD_MODELS[prop_model]
        props = list(
            prop_model.objects.filter(
                district__iexact=ad.district.strip(),
                street_no__iexact=pm.normalize_street_no(ad.street_no),
            ).prefetch_related(
                Prefetch(
                    'rent_ads',
                    queryset=(
                        rent_model.all_objects
                        .select_related('seller')
                        .prefetch_related('sightings')
                    ),
                ),
                Prefetch(
                    'sale_ads',
                    queryset=(
                        sale_model.all_objects
                        .select_related('seller')
                        .prefetch_related('sightings')
                    ),
                ),
            )
        )
        for prop in props:
            prop._linked_ads_cache = (
                list(prop.rent_ads.all()) + list(prop.sale_ads.all())
            )
        return props

    def _link_ad(self, ad, prop_model, blocks, counts, histogram):
        key = self._block_key(ad)
        if key not in blocks:
            blocks[key] = self._load_block(ad, prop_model)
        candidates = [
            prop for prop in blocks[key]
            if not ad.property_id or prop.pk != ad.property_id
        ]
        prop, score, decision = pm.match_property(
            ad,
            candidates,
            auto_threshold=self.auto_threshold,
            candidate_threshold=self.candidate_threshold,
        )
        histogram[round(min(score, 1.0), 1)] += 1

        if decision == 'auto':
            self._apply_link(ad, prop, score, counts, blocks[key])
        elif decision == 'candidate':
            ad.candidate_property = prop
            ad.property_match_status = 'candidate'
            ad.property_match_score = score
            self._save_ad(ad)
            counts['candidate'] += 1
        elif ad.property_id:
            # --relink: no better candidate found; keep current link.
            counts['kept'] += 1
        else:
            new_prop = prop_model.from_ad(ad)
            blocks[key].append(new_prop)
            ad.property = new_prop
            ad.candidate_property = None
            ad.property_match_status = 'auto'
            ad.property_match_score = score
            counts['new_property'] += 1
            if not self.dry_run:
                new_prop.save()
            self._save_ad(ad)

    def _apply_link(self, ad, prop, score, counts, block):
        if prop.pk is not None and ad.property_id == prop.pk:
            # --relink landed on the same property.
            counts['kept'] += 1
            return
        old_prop_id = ad.property_id
        ad.property = prop
        ad.candidate_property = None
        ad.property_match_status = 'auto'
        ad.property_match_score = score
        prop.note_linked_ad(ad)
        prop.refresh_from_ads(save=not self.dry_run)
        self._save_ad(ad)
        counts['auto_linked'] += 1
        if old_prop_id:
            self._vacate_property(
                old_prop_id, ad, block, type(prop)
            )

    def _vacate_property(self, old_prop_id, ad, block, prop_model):
        """Refresh or drop the property a --relink moved the ad off.

        ``block`` is the in-memory candidate list for this block — the
        old property may sit in it with a cached ad list that still
        contains ``ad``. An emptied property is deleted (same as the
        admin unlink action) so it can't attract false matches.
        """
        old_prop = next(
            (p for p in block if p.pk == old_prop_id), None
        )
        if old_prop is None:
            if self.dry_run:
                return
            old_prop = prop_model.objects.filter(
                pk=old_prop_id
            ).first()
            if old_prop is None:
                return
        old_prop.discard_linked_ad(ad)
        if old_prop.linked_ads():
            old_prop.refresh_from_ads(save=not self.dry_run)
            return
        if not self.dry_run:
            old_prop.delete()
        if old_prop in block:
            block.remove(old_prop)

    def _save_ad(self, ad):
        if self.dry_run:
            return
        ad.save(update_fields=[
            'property',
            'candidate_property',
            'property_match_status',
            'property_match_score',
        ])

    def _report(self, ad_model, counts, histogram):
        name = ad_model.__name__
        mode = 'DRY-RUN (nothing written)' if self.dry_run else 'WRITE'
        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(f'{name} — {mode}')
        self.stdout.write(f'{"=" * 60}')
        self.stdout.write(f'  Ads processed:     {counts["processed"]}')
        self.stdout.write(f'  New properties:    {counts["new_property"]}')
        self.stdout.write(f'  Auto-linked:       {counts["auto_linked"]}')
        self.stdout.write(f'  Review candidates: {counts["candidate"]}')
        if self.relink:
            self.stdout.write(f'  Kept existing:     {counts["kept"]}')
        if histogram:
            self.stdout.write('  Score histogram:')
            for bucket in sorted(histogram):
                self.stdout.write(
                    f'    {bucket:.1f}: {"#" * histogram[bucket]} '
                    f'({histogram[bucket]})'
                )
        logger.info(
            'link_ads_to_properties %s %s: %s',
            name, mode, dict(counts),
        )

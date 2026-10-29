"""
Read-only audit of the ad <-> property link state (plan F10).

Reports the anomaly flags defined in
``docs/plans/property_conflation_prevention_plan.md`` §3c plus the
same-block duplicate-property queue F14 consumes. Flags, in
severity order:

- TWIN_DIVERGED   — the same ad_id is linked to *different*
                    properties in the rent vs sale table
                    (property_match_status auto/manual). This is the
                    ``relink_property_ads --twin-fix`` queue
                    (~805 pairs on prod, 2026-10-29). Items whose
                    endpoint property's twins fan out to >=2
                    distinct targets are marked ``conflation`` —
                    the decisive mega-property signature.
- APTNO_CONFLICT  — a property whose linked ads carry >=2 distinct
                    non-empty apartment numbers (stored or
                    comment-extracted; apartments only).
- FLOOR_CONFLICT  — linked ads disagree on floor/max_floor
                    (apartments) or floors (houses), disagree on
                    rooms, or an ad's size deviates >15% from the
                    property's canonical size.
- COEXISTING      — subtype ``overlap``: one property holding >=2
                    same-deal ads from the same seller whose
                    first_seen..last_seen windows overlap >=2 days.
                    Subtype ``same_block``: two different properties
                    in the same block (district + normalized
                    street_no, same key as link_ads_to_properties)
                    that look like the same unit — matching
                    normalized street_name, equal rooms, size within
                    15%, non-conflicting apartment_no. This is the
                    ~326-cluster merge queue F14 consumes.
- BULK_ABSORB     — >=3 linked ads sharing one first_seen day, an
                    implausibly large ad set (>=8), or linked ads
                    spanning >1 distinct street_name or district —
                    the documented conflation signature of the
                    mega-properties.

This command NEVER writes to the database — it only reads. It is
safe to run against production.

Usage:
    python manage.py audit_property_links
    python manage.py audit_property_links --kind apartment
    python manage.py audit_property_links --limit 20 --verbose
    python manage.py audit_property_links --json
"""
import json
import logging
from collections import Counter, defaultdict
from itertools import combinations

from django.core.management.base import BaseCommand
from django.db.models import Prefetch

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

LINKED_STATUSES = ('auto', 'manual')
OVERLAP_MIN_DAYS = 2
BULK_SAME_DAY_MIN = 3
BULK_AD_SET_MIN = 8
DEFAULT_LIST_LIMIT = 50

FLAG_ORDER = [
    'TWIN_DIVERGED',
    'APTNO_CONFLICT',
    'FLOOR_CONFLICT',
    'COEXISTING',
    'BULK_ABSORB',
]

KINDS = {
    'apartment': (ApartmentProperty, ApartmentForRent,
                  ApartmentForSale),
    'house': (HouseProperty, HouseForRent, HouseForSale),
}


class Command(BaseCommand):
    help = (
        'Audit ad<->property links and report anomaly flags '
        '(read-only; never writes)'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--kind', '--type',
            dest='kind',
            choices=['apartment', 'house'],
            help='Limit to a single property kind (default: both)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=DEFAULT_LIST_LIMIT,
            help='Max items listed per flag in text output '
                 f'(default: {DEFAULT_LIST_LIMIT}; counts are '
                 'always complete)',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='List every flagged item, ignoring --limit',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Emit the full report as JSON instead of text',
        )

    def handle(self, *args, **options):
        kinds = (
            [options['kind']]
            if options['kind']
            else ['apartment', 'house']
        )
        report = {}
        for kind in kinds:
            report[kind] = self._audit_kind(kind)

        if options['json']:
            self.stdout.write(
                json.dumps(report, indent=2, default=str)
            )
        else:
            self._print_report(report, options)
        logger.info(
            'audit_property_links: %s',
            {
                kind: {
                    flag: len(items)
                    for flag, items in data['flags'].items()
                }
                for kind, data in report.items()
            },
        )

    # --- data collection -----------------------------------------

    def _audit_kind(self, kind):
        prop_model, rent_model, sale_model = KINDS[kind]
        props = list(
            prop_model.objects.order_by('pk').prefetch_related(
                Prefetch(
                    'rent_ads',
                    queryset=(
                        rent_model.all_objects
                        .select_related('seller')
                    ),
                ),
                Prefetch(
                    'sale_ads',
                    queryset=(
                        sale_model.all_objects
                        .select_related('seller')
                    ),
                ),
            )
        )
        for prop in props:
            prop._linked_ads_cache = (
                list(prop.rent_ads.all())
                + list(prop.sale_ads.all())
            )

        flags = {name: [] for name in FLAG_ORDER}
        divergent = self._audit_twins(rent_model, sale_model, flags)
        for prop in props:
            rent_ads = [
                a for a in prop._linked_ads_cache
                if isinstance(a, rent_model)
            ]
            sale_ads = [
                a for a in prop._linked_ads_cache
                if isinstance(a, sale_model)
            ]
            ads = prop._linked_ads_cache
            if not ads:
                continue
            if kind == 'apartment':
                self._audit_apt_nos(prop, ads, flags)
            self._audit_attributes(prop, ads, flags, kind)
            self._audit_overlap(prop, rent_ads, sale_ads, flags)
            self._audit_bulk(prop, ads, flags)
        self._audit_block_dups(props, flags)

        for name in FLAG_ORDER:
            flags[name].sort(key=self._item_sort_key)
        return {
            'properties_scanned': len(props),
            'linked_ads': sum(
                len(p._linked_ads_cache) for p in props
            ),
            'twin_divergent_props': sorted(divergent),
            'flags': flags,
        }

    @staticmethod
    def _item_sort_key(item):
        return (
            item.get('property')
            or (item.get('properties') or [0])[0]
            or 0,
            item.get('ad_id') or '',
        )

    def _audit_twins(self, rent_model, sale_model, flags):
        """Cross-deal twins linked to different properties.

        Returns the set of property pks whose linked ads' twins
        diverge to >=2 distinct targets — the decisive conflation
        signature from conflation plan §3c.
        """
        fields = (
            'ad_id', 'property_id', 'district', 'street_name',
            'street_no',
        )
        linked = dict(
            property_id__isnull=False,
            property_match_status__in=LINKED_STATUSES,
        )
        rent_links = {
            r[0]: r[1:]
            for r in rent_model.all_objects.filter(
                **linked
            ).values_list(*fields)
        }
        sale_links = {
            r[0]: r[1:]
            for r in sale_model.all_objects.filter(
                **linked
            ).values_list(*fields)
        }

        targets = defaultdict(set)  # prop pk -> twin-side prop pks
        for ad_id in sorted(set(rent_links) & set(sale_links)):
            r_prop = rent_links[ad_id][0]
            s_prop, district, street, no = sale_links[ad_id]
            if r_prop == s_prop:
                continue
            targets[r_prop].add(s_prop)
            targets[s_prop].add(r_prop)
            flags['TWIN_DIVERGED'].append({
                'flag': 'TWIN_DIVERGED',
                'ad_id': ad_id,
                'rent_property': r_prop,
                'sale_property': s_prop,
                'location': self._addr(district, street, no),
            })
        divergent = {
            pk for pk, tset in targets.items() if len(tset) >= 2
        }
        for item in flags['TWIN_DIVERGED']:
            item['conflation'] = (
                item['rent_property'] in divergent
                or item['sale_property'] in divergent
            )
        return divergent

    def _audit_apt_nos(self, prop, ads, flags):
        nos = defaultdict(list)
        for ad in ads:
            no = pm._ad_apartment_no(ad)
            if no:
                nos[no].append(ad.ad_id)
        if len(nos) < 2:
            return
        flags['APTNO_CONFLICT'].append({
            'flag': 'APTNO_CONFLICT',
            'property': prop.pk,
            'location': self._loc(prop),
            'ad_ids': [a.ad_id for a in ads],
            'detail': 'distinct apartment_nos: ' + ', '.join(
                f'{no} ({len(ids)} ad(s))'
                for no, ids in sorted(nos.items())
            ),
        })

    def _audit_attributes(self, prop, ads, flags, kind):
        problems = []
        floor_attr = 'floor' if kind == 'apartment' else 'floors'
        floors = {
            getattr(a, floor_attr) for a in ads
            if getattr(a, floor_attr, None) is not None
        }
        if len(floors) > 1:
            problems.append(f'{floor_attr}={sorted(floors)}')
        if kind == 'apartment':
            max_floors = {a.max_floor for a in ads}
            if len(max_floors) > 1:
                problems.append(f'max_floor={sorted(max_floors)}')
        rooms = {a.rooms for a in ads}
        if len(rooms) > 1:
            problems.append(f'rooms={sorted(rooms)}')
        off = [
            a.ad_id for a in ads
            if pm._size_too_different(a.size, prop.size)
        ]
        if off:
            problems.append(
                f'size>15% off canonical {prop.size}: {off}'
            )
        if not problems:
            return
        flags['FLOOR_CONFLICT'].append({
            'flag': 'FLOOR_CONFLICT',
            'property': prop.pk,
            'location': self._loc(prop),
            'ad_ids': [a.ad_id for a in ads],
            'detail': '; '.join(problems),
        })

    def _audit_overlap(self, prop, rent_ads, sale_ads, flags):
        hits = []
        for same_deal in (rent_ads, sale_ads):
            for a, b in combinations(same_deal, 2):
                if not self._same_seller(a, b):
                    continue
                overlap = (
                    min(a.last_seen.date(), b.last_seen.date())
                    - max(
                        a.first_seen.date(), b.first_seen.date()
                    )
                ).days
                if overlap >= OVERLAP_MIN_DAYS:
                    hits.append((a.ad_id, b.ad_id, overlap))
        if not hits:
            return
        flags['COEXISTING'].append({
            'flag': 'COEXISTING',
            'subtype': 'overlap',
            'property': prop.pk,
            'location': self._loc(prop),
            'ad_ids': sorted(
                {aid for a, b, _ in hits for aid in (a, b)}
            ),
            'detail': '; '.join(
                f'{a}+{b} overlap {d}d same seller'
                for a, b, d in hits
            ),
        })

    def _audit_bulk(self, prop, ads, flags):
        reasons = []
        day_counts = Counter(a.first_seen.date() for a in ads)
        bulk_days = {
            d.isoformat(): c
            for d, c in day_counts.items()
            if c >= BULK_SAME_DAY_MIN
        }
        if bulk_days:
            reasons.append(
                f'ads sharing a first_seen day: {bulk_days}'
            )
        if len(ads) >= BULK_AD_SET_MIN:
            reasons.append(f'{len(ads)} linked ads')
        streets = {
            pm.normalize_street_name(a.street_name) for a in ads
        }
        districts = {
            (a.district or '').strip().lower() for a in ads
        }
        if len(streets) > 1:
            reasons.append(f'street_names={sorted(streets)}')
        if len(districts) > 1:
            reasons.append(f'districts={sorted(districts)}')
        if not reasons:
            return
        flags['BULK_ABSORB'].append({
            'flag': 'BULK_ABSORB',
            'property': prop.pk,
            'location': self._loc(prop),
            'ad_ids': [a.ad_id for a in ads],
            'detail': '; '.join(reasons),
        })

    def _audit_block_dups(self, props, flags):
        """Different properties in one block that look identical.

        Block key mirrors link_ads_to_properties._block_key:
        (district.lower(), normalized street_no).
        """
        blocks = defaultdict(list)
        for prop in props:
            key = (
                prop.district.strip().lower(),
                pm.normalize_street_no(prop.street_no),
            )
            blocks[key].append(prop)
        for (district, street_no), plist in blocks.items():
            if len(plist) < 2:
                continue
            for p1, p2 in combinations(sorted(plist,
                                              key=lambda p: p.pk),
                                       2):
                if not self._same_unit(p1, p2):
                    continue
                flags['COEXISTING'].append({
                    'flag': 'COEXISTING',
                    'subtype': 'same_block',
                    'properties': [p1.pk, p2.pk],
                    'block': f'{district} | {street_no}',
                    'location': self._loc(p1),
                    'ad_ids': [
                        a.ad_id
                        for p in (p1, p2)
                        for a in p._linked_ads_cache
                    ],
                    'detail': (
                        f'props {p1.pk}+{p2.pk}: street '
                        f'{pm.normalize_street_name(p1.street_name)!r}'
                        f', {p1.rooms}rm, sizes {p1.size}/{p2.size}, '
                        f'floors '
                        f'{getattr(p1, "floor", getattr(p1, "floors", None))}'
                        f'/'
                        f'{getattr(p2, "floor", getattr(p2, "floors", None))}'
                    ),
                })

    # --- helpers --------------------------------------------------

    @staticmethod
    def _same_unit(p1, p2):
        """Do two same-block properties describe one unit?"""
        if pm.normalize_street_name(p1.street_name) != (
            pm.normalize_street_name(p2.street_name)
        ):
            return False
        if p1.rooms != p2.rooms:
            return False
        if pm._size_too_different(p1.size, p2.size):
            return False
        n1 = pm.normalize_apartment_no(
            getattr(p1, 'apartment_no', '')
        )
        n2 = pm.normalize_apartment_no(
            getattr(p2, 'apartment_no', '')
        )
        if n1 and n2 and n1 != n2:
            return False
        return True

    @staticmethod
    def _same_seller(a, b):
        if a.seller_id and a.seller_id == b.seller_id:
            return True
        sa, sb = pm._seller_or_none(a), pm._seller_or_none(b)
        if sa and sb:
            return bool(
                (sa.phone and sa.phone == sb.phone)
                or (
                    sa.contact_id
                    and sa.contact_id == sb.contact_id
                )
            )
        return False

    @staticmethod
    def _addr(district, street, no):
        return f'{district} | {street} {no}'.rstrip()

    @classmethod
    def _loc(cls, prop):
        return cls._addr(prop.district, prop.street_name,
                         prop.street_no)

    # --- reporting ------------------------------------------------

    def _print_report(self, report, options):
        limit = options['limit']
        verbose = options['verbose']
        self.stdout.write('=' * 60)
        self.stdout.write('audit_property_links — READ-ONLY')
        self.stdout.write('=' * 60)
        for kind, data in report.items():
            self.stdout.write(f'\n=== {kind} ===')
            self.stdout.write(
                f'  Properties scanned: '
                f'{data["properties_scanned"]:,}   '
                f'Linked ads: {data["linked_ads"]:,}'
            )
            for flag in FLAG_ORDER:
                if flag == 'APTNO_CONFLICT' and kind == 'house':
                    continue  # apartments only
                items = data['flags'][flag]
                line = f'  {flag}: {len(items):,}'
                if flag == 'TWIN_DIVERGED':
                    line += (
                        ' (props with >=2 divergent twin '
                        f'targets: '
                        f'{len(data["twin_divergent_props"])})'
                    )
                if flag == 'COEXISTING' and items:
                    subs = Counter(
                        i.get('subtype', '?') for i in items
                    )
                    line += ' (' + ', '.join(
                        f'{k}={v}'
                        for k, v in sorted(subs.items())
                    ) + ')'
                self.stdout.write(line)
                shown = items if verbose else items[:limit]
                for item in shown:
                    self.stdout.write(
                        f'    {self._format_item(item)}'
                    )
                remaining = len(items) - len(shown)
                if remaining > 0:
                    self.stdout.write(
                        f'    ... {remaining:,} more '
                        '(--verbose/--json for the full list)'
                    )

    @staticmethod
    def _format_item(item):
        if item['flag'] == 'TWIN_DIVERGED':
            mark = ' CONFLATION' if item.get('conflation') else ''
            return (
                f"{item['ad_id']} "
                f"rent_prop={item['rent_property']} "
                f"sale_prop={item['sale_property']} "
                f"{item['location']}{mark}"
            )
        if item.get('subtype') == 'same_block':
            return item['detail']
        return (
            f"prop={item.get('property')} "
            f"{item.get('location', '')} — {item['detail']} "
            f"ads={item.get('ad_ids', [])}"
        )

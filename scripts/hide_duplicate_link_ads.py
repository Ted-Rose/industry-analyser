"""
One-time data fix: hide duplicate classified-ad rows sharing a link.

Background: before commit b833b94 the scrapers built ad_id as the
ss.com tr_ row id plus concatenated listing-cell text, so one listing
could be stored as several rows under malformed ad_ids (e.g.
'tr_54290794Skolas 23606/6Spec. pr.' or a real id with extra digits
appended like 'tr_5788233925'). The tr_-prefix dedupe merged most of
these, but a residue remains: rows in the same table sharing the
exact same `link` under different ad_ids — literal duplicates of one
listing.

This script groups all_objects rows by `link`, keeps ONE canonical
row visible per group and sets is_hidden=True on the rest:

- canonical must be a visible row if the group has any visible rows
  (nothing already hidden is un-hidden just to change which row is
  canonical — a hidden canonical is only picked when ALL rows in the
  group are hidden);
- within that pool, ad_ids matching '^tr_\\d{7,9}$' (real ss.com ids)
  are preferred over malformed ones;
- ties break on most sightings, then earliest first_seen, then pk.

`last_seen` is preserved on hidden rows via F() — is_hidden is the
only field that changes. Sightings and property links are NOT moved;
hiding an ad does not merge property rows (that is tracked in
docs/property_match_review_2026_10.md).

Usage:
    python scripts/hide_duplicate_link_ads.py --dry-run
    python scripts/hide_duplicate_link_ads.py
"""
import argparse
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE', 'industry_analyser.settings'
)
django.setup()

from django.db import transaction  # noqa: E402
from django.db.models import Count, F  # noqa: E402
from classified_ads.models import (  # noqa: E402
    ApartmentForRent, ApartmentForSale, HouseForRent, HouseForSale,
)

logger = logging.getLogger('classified_ads')

REAL_AD_ID_RE = re.compile(r'^tr_\d{7,9}$')

TABLES = [
    ApartmentForRent,
    ApartmentForSale,
    HouseForRent,
    HouseForSale,
]


def collect_groups(ad_model):
    """Return {link: [ads]} for links with >1 row in the table."""
    dup_links = (
        ad_model.all_objects.values('link')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
        .values_list('link', flat=True)
    )
    groups = defaultdict(list)
    qs = ad_model.all_objects.filter(
        link__in=dup_links
    ).annotate(sighting_count=Count('sightings'))
    for ad in qs.iterator(chunk_size=2000):
        groups[ad.link].append(ad)
    return dict(groups)


def pick_canonical(rows):
    """
    Pick the row to keep visible. Returns (canonical, final_pool).

    Visible rows first (a hidden row is only canonical when every row
    in the group is hidden), then real tr_<7-9 digits> ad_ids, then
    most sightings, earliest first_seen, then pk.
    """
    visible = [r for r in rows if not r.is_hidden]
    pool = visible if visible else rows
    real_ids = [r for r in pool if REAL_AD_ID_RE.match(r.ad_id)]
    if real_ids:
        pool = real_ids
    pool.sort(
        key=lambda ad: (-ad.sighting_count, ad.first_seen, ad.pk)
    )
    return pool[0], pool


def is_ambiguous(pool, canonical):
    """True if another final-pool row ties on sightings+first_seen."""
    key = (-canonical.sighting_count, canonical.first_seen)
    rivals = [
        r for r in pool if r.pk != canonical.pk
        and (-r.sighting_count, r.first_seen) == key
    ]
    return bool(rivals)


def plan_table(ad_model, dry_run):
    """Build hide plans for one table; print the dry-run report."""
    table = ad_model._meta.db_table
    groups = collect_groups(ad_model)
    plans = []
    stats = {
        'groups': len(groups),
        'rows': sum(len(v) for v in groups.values()),
        'surplus': 0,
        'newly_hidden': 0,
        'already_hidden': 0,
        'split_property': 0,
        'all_hidden_groups': 0,
        'no_real_ad_id': 0,
        'ambiguous': 0,
        'hidden_linked': 0,
    }

    for link in sorted(groups):
        rows = groups[link]
        canonical, pool = pick_canonical(rows)
        to_hide = [r for r in rows if r.pk != canonical.pk]
        newly = [r for r in to_hide if not r.is_hidden]
        prop_ids = {r.property_id for r in rows}
        split = len(prop_ids) > 1
        all_hidden = all(r.is_hidden for r in rows)
        ambig = is_ambiguous(pool, canonical)
        stats['surplus'] += len(to_hide)
        stats['newly_hidden'] += len(newly)
        stats['already_hidden'] += len(to_hide) - len(newly)
        stats['split_property'] += 1 if split else 0
        stats['all_hidden_groups'] += 1 if all_hidden else 0
        stats['no_real_ad_id'] += (
            0 if any(REAL_AD_ID_RE.match(r.ad_id) for r in pool) else 1
        )
        stats['ambiguous'] += 1 if ambig else 0
        stats['hidden_linked'] += sum(
            1 for r in newly if r.property_id is not None
        )
        plans.append({
            'link': link,
            'canonical': canonical,
            'to_hide': to_hide,
            'newly': newly,
            'split': split,
            'all_hidden': all_hidden,
            'ambiguous': ambig,
        })

    print(f"\n=== {table} ===")
    print(
        f"  dup-link groups: {stats['groups']:,} | rows in groups: "
        f"{stats['rows']:,} | surplus (non-canonical): "
        f"{stats['surplus']:,}"
    )
    print(
        f"  to newly hide: {stats['newly_hidden']:,} | already hidden "
        f"(skip): {stats['already_hidden']:,} | newly hidden rows "
        f"with property link: {stats['hidden_linked']:,}"
    )
    print(
        f"  groups split across >1 property: "
        f"{stats['split_property']:,} | all-hidden groups: "
        f"{stats['all_hidden_groups']:,} | no real tr_ id in pool: "
        f"{stats['no_real_ad_id']:,} | ambiguous pick: "
        f"{stats['ambiguous']:,}"
    )
    if dry_run:
        for plan in plans:
            rows_desc = '  '.join(
                f"{r.ad_id}{'*' if r.is_hidden else ''}"
                f"(p={r.property_id},s={r.sighting_count})"
                for r in plan['to_hide'] + [plan['canonical']]
            )
            flags = []
            if plan['split']:
                flags.append('SPLIT-PROP')
            if plan['all_hidden']:
                flags.append('ALL-HIDDEN')
            if plan['ambiguous']:
                flags.append('AMBIG')
            flag_str = f" [{' '.join(flags)}]" if flags else ''
            print(
                f"  KEEP {plan['canonical'].ad_id} | HIDE "
                f"{', '.join(r.ad_id for r in plan['to_hide'])}"
                f"{flag_str}\n    {plan['link']}\n    {rows_desc}"
            )
    return plans, stats


def apply_plans(ad_model, plans):
    """Set is_hidden=True on every non-canonical visible row."""
    pks = [
        r.pk for plan in plans for r in plan['newly']
    ]
    if not pks:
        return 0
    with transaction.atomic():
        updated = ad_model.all_objects.filter(
            pk__in=pks, is_hidden=False
        ).update(is_hidden=True, last_seen=F('last_seen'))
    logger.info(
        "%s: hid %d duplicate-link rows", ad_model._meta.db_table,
        updated,
    )
    return updated


def main():
    parser = argparse.ArgumentParser(
        description='Hide duplicate classified-ad rows that share '
                    'the same link.'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Report what would change without writing anything',
    )
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN — no changes will be written")

    grand = 0
    for ad_model in TABLES:
        plans, _ = plan_table(ad_model, dry_run=args.dry_run)
        if args.dry_run:
            continue
        grand += apply_plans(ad_model, plans)

    if args.dry_run:
        print("\nDry run finished — re-run without --dry-run to apply.")
    else:
        print(f"\nDone. Total rows newly hidden: {grand:,}")


if __name__ == '__main__':
    main()

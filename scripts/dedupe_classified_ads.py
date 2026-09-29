"""
One-time data migration: merge duplicate classified-ad rows.

Background: ad_id used to be built as the ss.com row id ("tr_<n>")
plus concatenated listing-cell text, so the same ad was stored under
several ad_ids. The scrapers now use the bare tr_ id; this script
merges the historic duplicates:

- groups rows by the tr_ prefix embedded in ad_id,
- keeps the row with the most sightings (tie-break: earliest
  first_seen) as the canonical row,
- moves all sightings from duplicate rows onto the canonical row
  (unique_together(ad, seen_on) + ignore_conflicts dedupes overlaps),
- rewrites the canonical row's ad_id to the bare tr_ id and carries
  min(first_seen)/max(last_seen) across the group onto it,
- deletes the remaining duplicate rows (their own sightings cascade).

Each chunk of groups is merged in its own transaction. Run --dry-run
first.

Usage:
    python scripts/dedupe_classified_ads.py --dry-run
    python scripts/dedupe_classified_ads.py
    python scripts/dedupe_classified_ads.py --batch-size 500
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

from django.db import connection, transaction  # noqa: E402
from django.db.models import (  # noqa: E402
    Case, CharField, Count, DateTimeField, Value, When,
)
from classified_ads.models import (  # noqa: E402
    ApartmentForRent, ApartmentForRentSighting,
    ApartmentForSale, ApartmentForSaleSighting,
    HouseForRent, HouseForRentSighting,
    HouseForSale, HouseForSaleSighting,
)

logger = logging.getLogger('classified_ads')

TR_PREFIX_RE = re.compile(r'^(tr_\d+)')

TABLES = [
    (ApartmentForRent, ApartmentForRentSighting),
    (ApartmentForSale, ApartmentForSaleSighting),
    (HouseForRent, HouseForRentSighting),
    (HouseForSale, HouseForSaleSighting),
]


def group_by_tr_prefix(ad_model):
    """
    Return (groups, malformed) where groups maps tr_ prefix -> [ads]
    (only prefixes with >1 row) and malformed is a list of ad_ids that
    don't start with tr_<digits>.
    """
    groups = defaultdict(list)
    malformed = []
    qs = ad_model.all_objects.annotate(
        sighting_count=Count('sightings')
    )
    for ad in qs.iterator(chunk_size=2000):
        match = TR_PREFIX_RE.match(ad.ad_id)
        if not match:
            malformed.append(ad.ad_id)
            continue
        groups[match.group(1)].append(ad)
    return (
        {k: v for k, v in groups.items() if len(v) > 1},
        malformed,
    )


def plan_groups(groups):
    """
    Turn each dup group into a merge plan: canonical row (most
    sightings, tie-break earliest first_seen), the dupe pks to delete,
    and the consolidated first_seen/last_seen.
    """
    plans = []
    for tr_id, rows in groups.items():
        rows.sort(
            key=lambda ad: (-ad.sighting_count, ad.first_seen, ad.pk)
        )
        plans.append({
            'tr_id': tr_id,
            'canonical_pk': rows[0].pk,
            'dupe_pks': [ad.pk for ad in rows[1:]],
            'first_seen': min(ad.first_seen for ad in rows),
            'last_seen': max(ad.last_seen for ad in rows),
        })
    return plans


def merge_chunk(ad_model, sighting_model, plans):
    """
    Merge a chunk of dup groups in one transaction using bulk queries
    (per-group queries would be latency-bound against a remote DB).

    Sightings are copied to canonical rows before the dup rows are
    deleted so nothing is lost to the FK cascade; canonical rows are
    written via QuerySet.update() because save() would clobber
    first_seen/last_seen (auto_now_add/auto_now).
    """
    dupe_to_canonical = {}
    for plan in plans:
        for pk in plan['dupe_pks']:
            dupe_to_canonical[pk] = plan['canonical_pk']

    # (canonical pk, seen_on) pairs — a set because two dupes can hold
    # a sighting for the same day, which would map to the same pair.
    pairs = set()
    for dupe_pk, seen_on in sighting_model.objects.filter(
        ad_id__in=dupe_to_canonical.keys()
    ).values_list('ad_id', 'seen_on').iterator():
        pairs.add((dupe_to_canonical[dupe_pk], seen_on))

    sighting_model.objects.bulk_create(
        [
            sighting_model(ad_id=canonical_pk, seen_on=seen_on)
            for canonical_pk, seen_on in pairs
        ],
        ignore_conflicts=True,
    )

    # Delete dup rows before rewriting ad_id: a bare tr_ id row in the
    # group would otherwise collide on the unique constraint.
    ad_model.all_objects.filter(pk__in=dupe_to_canonical.keys()).delete()

    canonical_pks = [p['canonical_pk'] for p in plans]
    ad_model.all_objects.filter(pk__in=canonical_pks).update(
        ad_id=Case(
            *[When(pk=p['canonical_pk'], then=Value(p['tr_id']))
              for p in plans],
            output_field=CharField(),
        ),
        first_seen=Case(
            *[When(pk=p['canonical_pk'], then=Value(p['first_seen']))
              for p in plans],
            output_field=DateTimeField(),
        ),
        last_seen=Case(
            *[When(pk=p['canonical_pk'], then=Value(p['last_seen']))
              for p in plans],
            output_field=DateTimeField(),
        ),
    )

    dupe_count = len(dupe_to_canonical)
    return dupe_count, len(pairs)


def normalize_ad_ids(ad_model, dry_run):
    """
    Rewrite every remaining composite ad_id to its bare tr_ prefix.

    Singleton rows (unique tr_ prefix, nothing to merge) never pass
    through merge_chunk(), so without this pass they keep composite
    ad_ids and a future scrape of that ad would mint a bare-id dup.
    After merging, each tr_ prefix maps to exactly one row, so the
    rewrite can't collide. Postgres-only SQL (regex substring).
    """
    table = ad_model._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT count(*) FROM {table} "
            "WHERE ad_id ~ 'tr_[0-9]+' "
            "AND ad_id <> substring(ad_id from 'tr_[0-9]+')"
        )
        to_rewrite = cursor.fetchone()[0]
        if dry_run:
            print(f"  would rewrite {to_rewrite:,} composite ad_ids "
                  f"to bare tr_ ids")
            return
        cursor.execute(
            f"UPDATE {table} "
            "SET ad_id = substring(ad_id from 'tr_[0-9]+') "
            "WHERE ad_id ~ 'tr_[0-9]+' "
            "AND ad_id <> substring(ad_id from 'tr_[0-9]+')"
        )
        print(f"  rewrote {cursor.rowcount:,} composite ad_ids to "
              f"bare tr_ ids")


def dedupe_table(ad_model, sighting_model, dry_run, batch_size):
    table = ad_model._meta.db_table
    groups, malformed = group_by_tr_prefix(ad_model)

    total_rows = ad_model.all_objects.count()
    dup_rows = sum(len(v) - 1 for v in groups.values())

    print(f"\n=== {table} ===")
    print(f"  rows: {total_rows:,} | dup groups: {len(groups):,} | "
          f"dup rows to delete: {dup_rows:,}")
    if malformed:
        print(f"  WARNING: {len(malformed):,} ad_ids don't match "
              f"'tr_<digits>' prefix, skipped: {malformed[:5]}")

    plans = plan_groups(groups)
    sightings_to_move = 0
    if dry_run:
        for plan in plans:
            sightings_to_move += sighting_model.objects.filter(
                ad_id__in=plan['dupe_pks']
            ).count()
        print(f"  would merge {len(plans):,} groups | "
              f"would delete {dup_rows:,} rows | "
              f"would move {sightings_to_move:,} sightings")
        normalize_ad_ids(ad_model, dry_run=True)
        return

    deleted = moved = done = 0
    for i in range(0, len(plans), batch_size):
        chunk = plans[i:i + batch_size]
        with transaction.atomic():
            d, m = merge_chunk(ad_model, sighting_model, chunk)
        deleted += d
        moved += m
        done += len(chunk)
        if done % 1000 < batch_size or done == len(plans):
            print(f"  ...merged {done:,}/{len(plans):,} groups")
            logger.info(
                "%s: merged %d/%d groups", table, done, len(plans)
            )

    print(f"  merged {len(plans):,} groups | deleted {deleted:,} rows "
          f"| moved {moved:,} sightings")
    logger.info(
        "%s: merged %d groups, deleted %d rows, moved %d sightings",
        table, len(plans), deleted, moved,
    )
    normalize_ad_ids(ad_model, dry_run=False)


def main():
    parser = argparse.ArgumentParser(
        description='Merge duplicate classified-ad rows that share '
                    'the same ss.com tr_ id.'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Report what would change without writing anything',
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=500,
        help='Dup groups merged per transaction (default 500)',
    )
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN — no changes will be written")

    for ad_model, sighting_model in TABLES:
        dedupe_table(ad_model, sighting_model, args.dry_run,
                     args.batch_size)

    print("\nDone. Run 'python manage.py validate_sightings' to check "
          "sighting integrity.")


if __name__ == '__main__':
    main()

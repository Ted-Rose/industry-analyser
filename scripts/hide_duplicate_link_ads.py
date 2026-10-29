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

`--swap-canonical` runs a different fix for the 'frozen' residue the
dup-link pass left behind (docs/plans/
classified_ads_data_quality_implementation_plan.md F6): same-link
groups where every visible row carries a malformed ad_id while the
real bare-tr_ row sits hidden — scrapes keep updating the hidden
row, so the visible row is a dead end. The swap hides the malformed
visible row(s) and un-hides the canonical bare-tr_ row (the hidden
sibling matching a visible id's tr_ prefix is preferred; a bare-tr_
sibling that doesn't match is still un-hidden but logged as a
PREFIX-MISMATCH for review). A second sweep then hides remaining
malformed-but-visible rows whose real ad provably exists elsewhere —
a visible same-link sibling with a bare tr_ id, or the malformed
id's own tr_ prefix is another row's ad_id (a dup of a different
listing). Malformed rows with no canonical fallback are listed as
REVIEW and left visible — hiding the only copy of a live ad would
lose real data.

Sightings stay where they are in both modes: each row keeps the
sighting history written under its own ad_id; the composite row's
sightings are NOT transferred to the canonical row.

Usage:
    python scripts/hide_duplicate_link_ads.py --dry-run
    python scripts/hide_duplicate_link_ads.py
    python scripts/hide_duplicate_link_ads.py --swap-canonical \
        --dry-run
    python scripts/hide_duplicate_link_ads.py --swap-canonical
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


# --- F6: --swap-canonical mode ------------------------------------
# Fixes 'frozen' same-link groups the dup-link pass left behind: the
# only visible row(s) carry malformed ad_ids while the real bare
# tr_<digits> row is hidden, so scrapes update a row nobody can see.

# Bare ss.com row id — 'tr_5788233925' (real id + appended digits)
# and 'tr_54290794Skolas 23606/6' (id + cell text) are malformed.
BARE_AD_ID_RE = re.compile(r'^tr_\d+$')
TR_PREFIX_RE = re.compile(r'^(tr_\d+)')


def is_malformed(ad_id):
    """True when ad_id is not a bare ss.com tr_<digits> id."""
    return not BARE_AD_ID_RE.match(ad_id)


def tr_prefix(ad_id):
    """Return the leading tr_<digits> part of an ad_id, or None."""
    match = TR_PREFIX_RE.match(ad_id)
    return match.group(1) if match else None


def collect_frozen_groups(ad_model):
    """
    Return swap plans for 'frozen' same-link groups: every visible
    row has a malformed ad_id and at least one hidden sibling has a
    bare tr_<digits> id (the row live scrapes keep updating).

    Each plan: link, the malformed visible rows to hide, the hidden
    canonical to un-hide, every bare-id candidate, and whether the
    canonical's ad_id equals a visible row's tr_ prefix — a mismatch
    means the mapping was inferred, not proven, and gets logged for
    review.
    """
    plans = []
    for link, rows in sorted(collect_groups(ad_model).items()):
        visible = [r for r in rows if not r.is_hidden]
        if not visible or not all(
            is_malformed(r.ad_id) for r in visible
        ):
            continue
        hidden_bare = [
            r for r in rows
            if r.is_hidden and not is_malformed(r.ad_id)
        ]
        if not hidden_bare:
            continue
        prefixes = {tr_prefix(r.ad_id) for r in visible}
        exact = [r for r in hidden_bare if r.ad_id in prefixes]
        pool = sorted(
            exact or hidden_bare,
            key=lambda ad: (-ad.sighting_count, ad.first_seen, ad.pk),
        )
        plans.append({
            'link': link,
            'visible': visible,
            'canonical': pool[0],
            'candidates': hidden_bare,
            'prefix_match': bool(exact),
        })
    return plans


def collect_malformed_residue(ad_model, swapped_pks):
    """
    Bucket every other visible malformed-id row:

    - 'hide': the real ad provably exists — a visible same-link
      sibling carries a bare tr_ id, or the malformed id's own tr_
      prefix is another row's ad_id (a dup of a different listing);
    - 'review': standalone malformed id with no canonical row to
      fall back on. It may be the only copy of a live ad, so it is
      listed for manual review and left visible.

    'hide' entries are (row, reason) pairs; 'review' entries are
    bare rows.
    """
    rows = [
        r for r in ad_model.all_objects.filter(is_hidden=False)
        if is_malformed(r.ad_id) and r.pk not in swapped_pks
    ]
    links = {r.link for r in rows}
    siblings = defaultdict(list)
    if links:
        for ad in ad_model.all_objects.filter(link__in=links):
            siblings[ad.link].append(ad)
    bare_ids = set(
        ad_model.all_objects.filter(
            ad_id__regex=BARE_AD_ID_RE.pattern,
        ).values_list('ad_id', flat=True)
    )
    hide, review = [], []
    for ad in rows:
        if any(
            s.pk != ad.pk and not s.is_hidden
            and not is_malformed(s.ad_id)
            for s in siblings[ad.link]
        ):
            hide.append((ad, 'visible same-link tr_ sibling'))
            continue
        prefix = tr_prefix(ad.ad_id)
        if prefix and prefix in bare_ids:
            hide.append((ad, f'tr-prefix {prefix} is a row'))
        else:
            review.append(ad)
    return {'hide': hide, 'review': review}


def report_swap_table(ad_model, plans, residue):
    """Print the swap / residue-hide / review audit for one table."""
    print(f"\n=== {ad_model._meta.db_table} ===")
    to_hide = sum(len(p['visible']) for p in plans)
    print(
        f"  frozen groups: {len(plans):,} | malformed rows to hide: "
        f"{to_hide:,} | canonical rows to un-hide: {len(plans):,}"
    )
    for p in plans:
        canon = p['canonical']
        flags = '' if p['prefix_match'] else ' [PREFIX-MISMATCH]'
        print(
            f"  SWAP un-hide {canon.ad_id}(pk={canon.pk}) | hide "
            + ', '.join(
                f"{r.ad_id}(pk={r.pk})" for r in p['visible']
            )
            + f"{flags}\n    {p['link']}"
        )
        if not p['prefix_match']:
            print(
                "    no candidate matched the visible id's tr_ "
                "prefix; chose among: "
                + ', '.join(
                    f"{r.ad_id}(pk={r.pk})" for r in p['candidates']
                )
            )
    print(
        f"  residue: hide {len(residue['hide']):,} | "
        f"review-needed (left visible): {len(residue['review']):,}"
    )
    for ad, reason in residue['hide']:
        print(f"  HIDE pk={ad.pk} {ad.ad_id} [{reason}]\n    {ad.link}")
    for ad in residue['review']:
        print(f"  REVIEW pk={ad.pk} {ad.ad_id}\n    {ad.link}")


def _set_hidden(ad_model, pks, hidden, batch_size):
    """Flip is_hidden on pks in batches; last_seen preserved."""
    updated = 0
    for i in range(0, len(pks), batch_size):
        updated += ad_model.all_objects.filter(
            pk__in=pks[i:i + batch_size], is_hidden=not hidden,
        ).update(is_hidden=hidden, last_seen=F('last_seen'))
    return updated


def apply_swaps(ad_model, plans, residue, batch_size):
    """
    Apply one table's swap + residue-hide plan in one transaction;
    return (hidden, unhidden) counts. Sightings are not touched —
    they stay on the row they were recorded against.
    """
    hide_pks = (
        [r.pk for p in plans for r in p['visible']]
        + [ad.pk for ad, _ in residue['hide']]
    )
    unhide_pks = [p['canonical'].pk for p in plans]
    with transaction.atomic():
        hidden = _set_hidden(ad_model, hide_pks, True, batch_size)
        unhidden = _set_hidden(
            ad_model, unhide_pks, False, batch_size
        )
    logger.info(
        '%s: swap-canonical hid %d row(s), un-hid %d row(s) '
        '(%d frozen group(s), %d residue hide(s), %d review)',
        ad_model._meta.db_table, hidden, unhidden, len(plans),
        len(residue['hide']), len(residue['review']),
    )
    return hidden, unhidden


def swap_table(ad_model, dry_run, batch_size):
    """Plan, report and (unless dry_run) apply swaps for a table."""
    plans = collect_frozen_groups(ad_model)
    swapped_pks = {r.pk for p in plans for r in p['visible']}
    residue = collect_malformed_residue(ad_model, swapped_pks)
    report_swap_table(ad_model, plans, residue)
    if dry_run:
        return 0, 0
    for p in plans:
        if not p['prefix_match']:
            logger.warning(
                '%s: PREFIX-MISMATCH on %s — un-hid %s (pk=%s), hid '
                '%s; verify the mapping',
                ad_model._meta.db_table, p['link'],
                p['canonical'].ad_id, p['canonical'].pk,
                [r.ad_id for r in p['visible']],
            )
    return apply_swaps(ad_model, plans, residue, batch_size)


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
    parser.add_argument(
        '--swap-canonical',
        action='store_true',
        help='F6 mode: swap frozen visible malformed-id rows with '
             'their hidden bare-tr_ siblings, then sweep remaining '
             'malformed visible ids (default: dup-link hide mode)',
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=500,
        help='Rows written per UPDATE batch in --swap-canonical '
             'mode (default 500)',
    )
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN — no changes will be written")

    if args.swap_canonical:
        hid = unhid = 0
        for ad_model in TABLES:
            h, u = swap_table(
                ad_model, args.dry_run, args.batch_size
            )
            hid += h
            unhid += u
        print(
            "\nSightings are NOT moved — each row keeps the "
            "sighting history written under its own ad_id."
        )
        if args.dry_run:
            print(
                "Dry run finished — re-run without --dry-run to "
                "apply."
            )
        else:
            print(
                f"Done. Rows hidden: {hid:,} | un-hidden: "
                f"{unhid:,}"
            )
        return

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

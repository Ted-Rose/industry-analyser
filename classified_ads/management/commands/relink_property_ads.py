"""
Consolidate cross-deal twin pairs onto one property (plan F4,
conflation plan §3c-§3d).

Background: ~805 ad_ids were scraped into BOTH the rent and sale
table of the same kind (apartment pair, house pair) and ended up
linked to DIFFERENT property rows — the TWIN_DIVERGED queue
reported by ``audit_property_links``. ``--twin-fix`` re-points
the rent row's ``property`` FK to the sale twin's property (the
rent row is usually the later/misclassified duplicate; the sale
side is the canonical target), stamps the move as an audit-driven
manual link (``property_match_status='manual'``, score 1.0),
clears ``candidate_property``, then refreshes canonical fields on
BOTH endpoint properties and deletes the source property when no
linked ads remain — the same orphan semantics as the admin unlink
action (``property_links.refresh_or_delete_vacated``).

Safety — pairs are NOT moved and go to the review list when:

- the two ads disagree on attributes (rooms mismatch or >15%
  size diff — the documented repurposed-listing cases),
- an endpoint property fails conflation sanity: it already holds
  >=2 distinct apartment numbers among its linked ads, or sits in
  the >=2-target twin fan-out signature from §3c,
- the rent ad fails the twin hard gates against the target
  property (consistent with ``link_ads_to_properties``'s
  ``_twin_link``).

A rent row flagged ``is_sale_misclassified`` is still relinked —
it IS the same physical unit; the flag is orthogonal to property
linkage — but logged and counted separately.

Each pair's move runs inside ``transaction.atomic`` and the
command is idempotent: pairs whose FKs already agree are filtered
out by the ``!=`` pair query, so a re-run is a no-op.

Usage:
    python manage.py relink_property_ads --twin-fix --dry-run
    python manage.py relink_property_ads --twin-fix \\
        --kind apartment --limit 50
"""
import logging
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from classified_ads import property_links as plinks
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

KINDS = {
    'apartment': (ApartmentProperty, ApartmentForRent,
                  ApartmentForSale),
    'house': (HouseProperty, HouseForRent, HouseForSale),
}

# Score stamped on audit-driven relinks — the twin link is treated
# as decisive evidence, same as the matcher's twin shortcut.
RELINK_SCORE = 1.0


class Command(BaseCommand):
    help = (
        'Repair ad<->property links (audit-driven relink; '
        'currently only --twin-fix)'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--twin-fix',
            action='store_true',
            help='Move diverged cross-deal twin pairs onto the '
                 "sale twin's property (required mode flag)",
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print the full planned moves without writing',
        )
        parser.add_argument(
            '--kind', '--type',
            dest='kind',
            choices=['apartment', 'house'],
            help='Limit to a single property kind (default: both)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Max twin pairs to process per kind',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Progress print interval in pairs (default: 500)',
        )

    def handle(self, *args, **options):
        if not options['twin_fix']:
            raise CommandError('specify a mode: --twin-fix')
        self.dry_run = options['dry_run']
        self.batch_size = options['batch_size']
        kinds = (
            [options['kind']]
            if options['kind']
            else ['apartment', 'house']
        )
        totals = defaultdict(int)
        moved_audit = []
        for kind in kinds:
            counts, review, moved = self._fix_kind(
                kind, *KINDS[kind], options['limit']
            )
            self._report_kind(kind, counts, review)
            for key, value in counts.items():
                totals[key] += value
            moved_audit.extend(moved)
        mode = 'DRY-RUN' if self.dry_run else 'WRITE'
        logger.info(
            'relink_property_ads --twin-fix %s: %s',
            mode, dict(totals),
        )
        logger.info(
            'twin-fix pk audit list (rent_ad_pk, from_prop, '
            'to_prop, source_outcome): %s',
            moved_audit,
        )

    # --- pair processing ------------------------------------------

    def _fix_kind(self, kind, prop_model, rent_model, sale_model,
                  limit):
        pairs = plinks.diverged_twin_pairs(rent_model, sale_model)
        fanout = plinks.twin_fanout_props(pairs)
        if limit:
            pairs = pairs[:limit]
        counts = defaultdict(int)
        review = []
        moved = []
        for ad_id, r_prop_id, s_prop_id in pairs:
            counts['found'] += 1
            self._move_pair(
                prop_model, rent_model, sale_model,
                ad_id, r_prop_id, s_prop_id, fanout,
                counts, review, moved,
            )
            if counts['found'] % self.batch_size == 0:
                self.stdout.write(
                    f'  ... processed {counts["found"]}'
                )
        return counts, review, moved

    def _move_pair(self, prop_model, rent_model, sale_model,
                   ad_id, r_prop_id, s_prop_id, fanout,
                   counts, review, moved):
        rent_ad = rent_model.all_objects.filter(ad_id=ad_id).first()
        sale_ad = sale_model.all_objects.filter(ad_id=ad_id).first()
        # Re-check against fresh state — the command is resumable
        # and a previous pair's move/delete may have changed the
        # precomputed endpoints.
        if (
            rent_ad is None or sale_ad is None
            or rent_ad.property_id != r_prop_id
            or sale_ad.property_id != s_prop_id
        ):
            counts['skipped_stale'] += 1
            return
        source = prop_model.objects.filter(pk=r_prop_id).first()
        target = prop_model.objects.filter(pk=s_prop_id).first()
        if source is None or target is None:
            counts['skipped_stale'] += 1
            return

        reasons = self._skip_reasons(
            rent_ad, sale_ad, source, target, fanout
        )
        if reasons:
            counts['skipped_conflict'] += 1
            review.append(
                (ad_id, rent_ad.pk, r_prop_id, s_prop_id, reasons)
            )
            return

        if rent_ad.is_sale_misclassified:
            counts['misclassified'] += 1
            logger.info(
                'twin-fix: rent ad %s (pk=%s) is_sale_misclassified'
                ' — relinking anyway; the flag is orthogonal to '
                'property linkage',
                ad_id, rent_ad.pk,
            )

        plan = (
            f'{ad_id}: rent_ad pk={rent_ad.pk} '
            f'prop {r_prop_id} -> {s_prop_id}'
        )
        with transaction.atomic():
            if self.dry_run:
                # Simulate the move in memory so refresh/vacate
                # see the post-move state without any writes.
                target._linked_ads_cache = (
                    target.linked_ads() + [rent_ad]
                )
            else:
                rent_ad.property = target
                rent_ad.candidate_property = None
                rent_ad.property_match_status = 'manual'
                rent_ad.property_match_score = RELINK_SCORE
                rent_ad.save(update_fields=[
                    'property',
                    'candidate_property',
                    'property_match_status',
                    'property_match_score',
                ])
            target.refresh_from_ads(save=not self.dry_run)
            outcome = plinks.refresh_or_delete_vacated(
                source, rent_ad, self.dry_run
            )
        verb = 'MOVE' if self.dry_run else 'MOVED'
        self.stdout.write(f'  {verb} {plan} (source {outcome})')
        counts['moved'] += 1
        counts[f'props_{outcome}'] += 1
        moved.append(
            (rent_ad.pk, r_prop_id, s_prop_id, outcome)
        )
        logger.info(
            'twin-fix %s %s',
            'would-move' if self.dry_run else 'moved', plan,
        )

    @staticmethod
    def _skip_reasons(rent_ad, sale_ad, source, target, fanout):
        """Reasons this pair must NOT move; empty list = move."""
        reasons = []
        if rent_ad.rooms != sale_ad.rooms:
            reasons.append(
                f'rooms conflict: {rent_ad.rooms} vs '
                f'{sale_ad.rooms}'
            )
        if pm._size_too_different(rent_ad.size, sale_ad.size):
            reasons.append(
                f'size conflict >15%: {rent_ad.size} vs '
                f'{sale_ad.size}'
            )
        # Conflation sanity on both endpoints — a property that
        # already holds >=2 distinct apartment numbers, or sits in
        # the >=2-target twin fan-out signature, is a suspect
        # merge endpoint (conflation plan §3c/§3d).
        for label, prop in (('source', source), ('target', target)):
            if prop.pk in fanout:
                reasons.append(
                    f'{label} prop {prop.pk} fans out to >=2 '
                    'twin targets'
                )
                continue
            nos = pm._property_apartment_nos(prop)
            if len(nos) >= 2:
                reasons.append(
                    f'{label} prop {prop.pk} holds >=2 apt_nos '
                    f'{sorted(nos)}'
                )
        # Twin hard gates vs the target property — consistent
        # with link_ads_to_properties._twin_link (§3a.1): a
        # repurposed listing lands in review, not in a merge.
        ad_no = pm._ad_apartment_no(rent_ad)
        target_nos = pm._property_apartment_nos(target)
        if pm._hard_reject(rent_ad, target, ad_no, target_nos):
            reasons.append(
                f'hard-gate vs target prop {target.pk}'
            )
        return reasons

    # --- reporting -------------------------------------------------

    def _report_kind(self, kind, counts, review):
        mode = 'DRY-RUN (nothing written)' if self.dry_run \
            else 'WRITE'
        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(f'{kind} — {mode}')
        self.stdout.write(f'{"=" * 60}')
        self.stdout.write(
            f'  Twin pairs found:       {counts["found"]}'
        )
        verb = 'Would move' if self.dry_run else 'Moved'
        self.stdout.write(
            f'  {verb}:             {counts["moved"]}'
        )
        self.stdout.write(
            f'  of which misclassified: {counts["misclassified"]}'
        )
        self.stdout.write(
            f'  Skipped (review):       '
            f'{counts["skipped_conflict"]}'
        )
        self.stdout.write(
            f'  Skipped (stale):        '
            f'{counts["skipped_stale"]}'
        )
        self.stdout.write(
            f'  Source props refreshed: '
            f'{counts["props_refreshed"]}'
        )
        self.stdout.write(
            f'  Source props deleted:   '
            f'{counts["props_deleted"]}'
        )
        if review:
            self.stdout.write('  Review list (not moved):')
            for ad_id, ad_pk, r_pk, s_pk, reasons in review:
                self.stdout.write(
                    f'    {ad_id} rent_pk={ad_pk} '
                    f'{r_pk} -> {s_pk}: {"; ".join(reasons)}'
                )
            logger.info(
                'twin-fix review list (%s): %s', kind, review,
            )

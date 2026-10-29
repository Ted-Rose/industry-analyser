"""
Consolidate cross-deal twin pairs onto one property (plan F4,
conflation plan §3c-§3d) and merge same-block duplicate-property
clusters (plan F14).

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

``--merge-same-block`` (plan F14)
---------------------------------

The audit's COEXISTING/same_block queue (~326 clusters on prod):
different property rows in one block that describe the same
physical unit (``property_links.same_block_dup_pairs`` — same
normalized street_name, equal rooms, size within 15%, compatible
apartment_no). Pairs are unioned into clusters; per cluster a
SURVIVOR is picked deterministically — most linked ads, tie-break
lowest pk — every non-survivor's linked ads are re-pointed to it
(status 'manual', score 1.0, ``candidate_property`` cleared), the
survivor is ``refresh_from_ads()``'d and each emptied victim is
deleted via ``property_links.delete_if_orphan``.

DESTRUCTIVE-ADJACENT: merged property rows cannot be cleanly
unmerged (the victim row is deleted and its ads' split identity is
lost). The mode therefore refuses to run without an explicit
selection: ``--pks`` approves a human-reviewed list of property
pks (a cluster merges only when EVERY member pk is listed), or
``--auto`` processes every cluster that passes the safety gates —
intended for dry-run exploration; prod runs should be driven from
a reviewed ``--pks`` list built off ``audit_property_links
--json``.

Safety gates — a cluster is NOT merged and goes to the review
list when ANY holds (all evaluated on fresh per-cluster state):

- the members no longer form a same-unit clique (a prop changed
  since the queue was computed, or union-chained members
  pairwise-conflict),
- the post-merge property would hold >=2 distinct non-empty
  apartment numbers across member props and their linked ads
  (conflicting decisive evidence),
- a member sits in the >=2-target twin fan-out conflation
  signature (§3c),
- a moved ad fails the matcher hard gates against the survivor
  (rooms mismatch, >15% size diff, apt_no conflict),
- the simulated post-merge linked-ad set trips
  ``property_matcher.conflation_alarms`` (floor dissent, same
  seller overlapping same-deal ads, multi apt_no), or would put
  >=2 same-deal-type ads from DIFFERENT sellers on one property —
  a documented conservative approximation of the COEXISTING
  alarm shape (two agencies listing 'the same' flat often means
  two different flats).

Each cluster merges inside ``transaction.atomic``; the command is
idempotent — merged clusters leave the same_block queue, so a
re-run is a no-op.

Usage:
    python manage.py relink_property_ads --twin-fix --dry-run
    python manage.py relink_property_ads --twin-fix \\
        --kind apartment --limit 50
    python manage.py relink_property_ads --merge-same-block \\
        --auto --dry-run
    python manage.py relink_property_ads --merge-same-block \\
        --pks 12,34,56 --kind apartment
    python manage.py relink_property_ads --merge-same-block \\
        --pks reviewed_merge_pks.txt
"""
import logging
import os
import re
from collections import defaultdict
from itertools import combinations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Prefetch

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
        'Repair ad<->property links (audit-driven relink: '
        '--twin-fix or --merge-same-block)'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--twin-fix',
            action='store_true',
            help='Move diverged cross-deal twin pairs onto the '
                 "sale twin's property (mode flag)",
        )
        parser.add_argument(
            '--merge-same-block',
            action='store_true',
            help='Merge same-block duplicate-property clusters '
                 'onto a survivor (mode flag; DESTRUCTIVE-'
                 'ADJACENT — requires --pks or --auto)',
        )
        parser.add_argument(
            '--pks',
            metavar='PK[,PK...]|FILE',
            help='With --merge-same-block: approved property pks '
                 'from a human-reviewed audit list — a comma-'
                 'separated list or a file path (pks separated by '
                 'commas/whitespace, # comments allowed). A '
                 'cluster merges only when EVERY member pk is '
                 'approved',
        )
        parser.add_argument(
            '--auto',
            action='store_true',
            help='With --merge-same-block: process every '
                 'discovered cluster that passes the safety '
                 'gates (prefer --pks on prod)',
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
            help='Max twin pairs / merge clusters to process '
                 'per kind',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Progress print interval in pairs/clusters '
                 '(default: 500)',
        )

    def handle(self, *args, **options):
        modes = [options['twin_fix'], options['merge_same_block']]
        if sum(bool(m) for m in modes) != 1:
            raise CommandError(
                'specify exactly one mode: '
                '--twin-fix or --merge-same-block'
            )
        if options['batch_size'] < 1:
            raise CommandError('--batch-size must be >= 1')
        self.dry_run = options['dry_run']
        self.batch_size = options['batch_size']
        if options['merge_same_block']:
            self._handle_merge(options)
            return
        if options['pks'] or options['auto']:
            raise CommandError(
                '--pks/--auto only apply to --merge-same-block'
            )
        self._handle_twin_fix(options)

    # --- mode dispatch --------------------------------------------

    def _handle_twin_fix(self, options):
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
            'twin-fix pk audit list (ad_id, rent_ad_pk, '
            'from_prop, to_prop, source_outcome): %s',
            moved_audit,
        )

    def _handle_merge(self, options):
        if options['pks'] and options['auto']:
            raise CommandError(
                '--pks and --auto are mutually exclusive'
            )
        if not options['pks'] and not options['auto']:
            raise CommandError(
                '--merge-same-block is destructive-adjacent and '
                'refuses to run unscoped: pass --pks with a '
                'human-reviewed list of approved property pks '
                '(from audit_property_links --json), or --auto '
                'to process every gate-clean cluster'
            )
        approved = (
            self._parse_pks(options['pks'])
            if options['pks']
            else None
        )
        kinds = (
            [options['kind']]
            if options['kind']
            else ['apartment', 'house']
        )
        totals = defaultdict(int)
        merged_audit = []
        for kind in kinds:
            counts, review, merged = self._merge_kind(
                kind, *KINDS[kind], approved, options['limit']
            )
            self._report_merge(kind, counts, review, approved)
            for key, value in counts.items():
                totals[key] += value
            merged_audit.extend(merged)
        mode = 'DRY-RUN' if self.dry_run else 'WRITE'
        logger.info(
            'relink_property_ads --merge-same-block %s '
            '(approved=%s): %s',
            mode,
            'auto' if approved is None else sorted(approved),
            dict(totals),
        )
        logger.info(
            'merge-same-block pk audit list '
            '(survivor, victims, moved_ad_pks, '
            'victim_outcomes): %s',
            merged_audit,
        )

    @staticmethod
    def _parse_pks(raw):
        """Approved property pks from a list or a file path."""
        if os.path.exists(raw):
            with open(raw) as handle:
                text = re.sub(r'#.*', '', handle.read())
        else:
            text = raw
        pks = set()
        for token in re.split(r'[\s,]+', text):
            if not token:
                continue
            try:
                pks.add(int(token))
            except ValueError:
                raise CommandError(
                    f'--pks: bad property pk token {token!r}'
                )
        return pks

    # --- pair processing ------------------------------------------

    def _fix_kind(self, kind, prop_model, rent_model, sale_model,
                  limit):
        pairs = plinks.diverged_twin_pairs(rent_model, sale_model)
        # Fanout is computed over the FULL diverged set even when
        # --limit truncates processing — intentionally
        # conservative: a prop that fans out across pairs beyond
        # the limit is still conflation-suspect.
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
            review.append((
                ad_id,
                getattr(rent_ad, 'pk', None),
                r_prop_id,
                s_prop_id,
                ['stale: ad links changed since pair list'],
            ))
            return
        source = prop_model.objects.filter(pk=r_prop_id).first()
        target = prop_model.objects.filter(pk=s_prop_id).first()
        if source is None or target is None:
            counts['skipped_stale'] += 1
            review.append((
                ad_id,
                rent_ad.pk,
                r_prop_id,
                s_prop_id,
                ['stale: endpoint property missing'],
            ))
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
            (ad_id, rent_ad.pk, r_prop_id, s_prop_id, outcome)
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
        # Target apt_nos also feed the hard gate below — compute
        # once, reuse inside the endpoint loop.
        target_nos = pm._property_apartment_nos(target)
        for label, prop in (('source', source), ('target', target)):
            if prop.pk in fanout:
                reasons.append(
                    f'{label} prop {prop.pk} fans out to >=2 '
                    'twin targets'
                )
                continue
            nos = (
                target_nos if label == 'target'
                else pm._property_apartment_nos(prop)
            )
            if len(nos) >= 2:
                reasons.append(
                    f'{label} prop {prop.pk} holds >=2 apt_nos '
                    f'{sorted(nos)}'
                )
        # Twin hard gates vs the target property — consistent
        # with link_ads_to_properties._twin_link (§3a.1): a
        # repurposed listing lands in review, not in a merge.
        ad_no = pm._ad_apartment_no(rent_ad)
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

    # --- same-block merge -----------------------------------------

    @staticmethod
    def _load_props(prop_model, rent_model, sale_model, **filters):
        """Properties with their linked-ad lists hydrated.

        ``_linked_ads_cache`` is set from prefetched
        ``rent_ads``/``sale_ads`` (``all_objects`` — hidden and
        misclassified ads still carry their link) so gates,
        ``iter_linked_ads`` and ``refresh_from_ads`` all read the
        same snapshot.
        """
        props = list(
            prop_model.objects.filter(**filters).order_by('pk')
            .prefetch_related(
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
        return props

    @staticmethod
    def _clusters(pairs):
        """Union same-unit pairs into clusters (union-find).

        Returns member lists sorted by pk, clusters ordered by
        lowest member pk. Transitivity is NOT trusted — a cluster
        whose members pairwise-conflict is sent to review by the
        clique gate, not merged.
        """
        parent = {}

        def find(pk):
            parent.setdefault(pk, pk)
            while parent[pk] != pk:
                parent[pk] = parent[parent[pk]]
                pk = parent[pk]
            return pk

        members = {}
        for p1, p2 in pairs:
            members[p1.pk] = p1
            members[p2.pk] = p2
            parent[find(p1.pk)] = find(p2.pk)
        groups = defaultdict(list)
        for pk, prop in members.items():
            groups[find(pk)].append(prop)
        clusters = [
            sorted(group, key=lambda p: p.pk)
            for group in groups.values()
        ]
        return sorted(clusters, key=lambda g: g[0].pk)

    def _merge_kind(self, kind, prop_model, rent_model, sale_model,
                    approved, limit):
        props = self._load_props(prop_model, rent_model, sale_model)
        pairs = plinks.same_block_dup_pairs(props)
        # Fan-out is computed over the FULL diverged set even when
        # --limit truncates processing — same conservatism as
        # --twin-fix.
        fanout = plinks.twin_fanout_props(
            plinks.diverged_twin_pairs(rent_model, sale_model)
        )
        clusters = self._clusters(pairs)
        if limit:
            clusters = clusters[:limit]
        counts = defaultdict(int)
        review = []
        merged = []
        for members in clusters:
            counts['found'] += 1
            member_pks = [p.pk for p in members]
            if approved is not None and not (
                set(member_pks) <= approved
            ):
                counts['not_approved'] += 1
                continue
            self._merge_cluster(
                prop_model, rent_model, sale_model,
                member_pks, fanout, counts, review, merged,
            )
            if counts['found'] % self.batch_size == 0:
                self.stdout.write(
                    f'  ... processed {counts["found"]}'
                )
        return counts, review, merged

    def _merge_cluster(self, prop_model, rent_model, sale_model,
                       member_pks, fanout, counts, review, merged):
        # Re-fetch fresh state inside the unit of work — the
        # queue snapshot may be stale (command is resumable and a
        # scrape may run between queue build and merge).
        members = self._load_props(
            prop_model, rent_model, sale_model, pk__in=member_pks
        )
        if len(members) != len(member_pks):
            counts['skipped_stale'] += 1
            review.append((
                tuple(member_pks),
                ['stale: a member property vanished since the '
                 'queue was built'],
            ))
            return
        reasons = self._merge_skip_reasons(members, fanout)
        if reasons:
            counts['skipped_review'] += 1
            review.append((tuple(member_pks), reasons))
            return

        survivor = min(
            members, key=lambda p: (-len(p.linked_ads()), p.pk)
        )
        victims = [p for p in members if p.pk != survivor.pk]
        moves = [
            (victim, list(victim.linked_ads()))
            for victim in victims
        ]
        moved_ads = [ad for _, ads in moves for ad in ads]
        # delete() clears victim.pk — capture before the merge.
        victim_pks = [v.pk for v, _ in moves]

        verb = 'MERGE' if self.dry_run else 'MERGED'
        self.stdout.write(
            f'  {verb} cluster {member_pks}: '
            f'survivor={survivor.pk}'
        )
        for victim, ads in moves:
            self.stdout.write(
                f'    victim {victim.pk}: '
                f'{len(ads)} ad(s) '
                f'{sorted(a.ad_id for a in ads)}'
            )

        with transaction.atomic():
            if not self.dry_run:
                for ad in moved_ads:
                    ad.property = survivor
                    ad.candidate_property = None
                    ad.property_match_status = 'manual'
                    ad.property_match_score = RELINK_SCORE
                    ad.save(update_fields=[
                        'property',
                        'candidate_property',
                        'property_match_status',
                        'property_match_score',
                    ])
            # Simulate/write the post-merge linked-ad list on the
            # survivor cache so refresh sees the same state on
            # both paths.
            survivor._linked_ads_cache = (
                list(survivor.iter_linked_ads()) + moved_ads
            )
            survivor.refresh_from_ads(save=not self.dry_run)
            outcomes = []
            for victim, _ in moves:
                if self.dry_run:
                    # Every linked ad moved off — the victim is
                    # guaranteed emptied.
                    outcomes.append('deleted')
                else:
                    victim._linked_ads_cache = []
                    outcomes.append(
                        'deleted'
                        if plinks.delete_if_orphan(victim)
                        else 'kept'
                    )
        counts['merged'] += 1
        counts['ads_moved'] += len(moved_ads)
        for outcome in outcomes:
            counts[f'victims_{outcome}'] += 1
        merged.append((
            survivor.pk,
            victim_pks,
            [a.pk for a in moved_ads],
            outcomes,
        ))
        logger.info(
            'merge-same-block %s cluster %s: survivor=%s '
            'victims=%s moved_ad_pks=%s outcomes=%s',
            'would-merge' if self.dry_run else 'merged',
            member_pks, survivor.pk,
            victim_pks,
            [a.pk for a in moved_ads],
            outcomes,
        )

    @staticmethod
    def _seller_groups(ads):
        """Group ads by seller identity.

        ``property_matcher._same_seller_pair`` is the identity
        test (seller row, phone or contact_id). Ads with no
        resolvable seller are unattributed and skipped — they
        cannot accuse a merge of mixing sellers.
        """
        groups = []
        for ad in ads:
            if pm._seller_or_none(ad) is None:
                continue
            for group in groups:
                if pm._same_seller_pair(ad, group[0]):
                    group.append(ad)
                    break
            else:
                groups.append([ad])
        return groups

    @staticmethod
    def _merge_skip_reasons(members, fanout):
        """Reasons this cluster must NOT merge; [] = merge."""
        reasons = []
        ordered = sorted(members, key=lambda p: p.pk)

        # Clique re-check on fresh state — union-find chains
        # pairs transitively, but a-b and b-c being same-unit
        # does not prove a-c is (empty-apt_no members can bridge
        # two conflicting apt numbers).
        for p1, p2 in combinations(ordered, 2):
            if not plinks.same_unit(p1, p2):
                reasons.append(
                    f'props {p1.pk}+{p2.pk} are not same-unit '
                    '(stale queue or apt_no conflict through a '
                    'bridge member)'
                )
        # Conflation signature: a member whose cross-deal twins
        # fan out to >=2 distinct properties is absorbing
        # unrelated units (§3c) — never a merge endpoint.
        for prop in ordered:
            if prop.pk in fanout:
                reasons.append(
                    f'prop {prop.pk} sits in the >=2-target '
                    'twin fan-out conflation signature'
                )
        # Post-merge apartment-number union — >=2 distinct
        # non-empty numbers across member props and their linked
        # ads is conflicting decisive evidence.
        survivor = min(
            ordered, key=lambda p: (-len(p.linked_ads()), p.pk)
        )
        post_nos = set()
        for prop in ordered:
            post_nos |= pm._property_apartment_nos(prop)
        if len(post_nos) >= 2:
            reasons.append(
                'post-merge property would hold >=2 distinct '
                f'apt_nos {sorted(post_nos)}'
            )
        moved_ads = [
            ad
            for prop in ordered if prop.pk != survivor.pk
            for ad in prop.linked_ads()
        ]
        # Matcher hard gates vs the survivor, per moved ad —
        # consistent with the twin-fix safety checks.
        for ad in moved_ads:
            ad_no = pm._ad_apartment_no(ad)
            if pm._hard_reject(ad, survivor, ad_no, post_nos):
                reasons.append(
                    f'ad {ad.ad_id} fails the hard gates vs '
                    f'survivor prop {survivor.pk} '
                    '(rooms/size/apt_no)'
                )
        # Post-merge conflation alarms on the simulated linked-ad
        # set: floor dissent, same-seller overlapping same-deal
        # ads (batch absorption), multi apt_no.
        linked_post = list(survivor.linked_ads()) + moved_ads
        alarms = set()
        for ad in moved_ads:
            alarms |= pm.conflation_alarms(
                ad, survivor, post_nos, linked_post
            )
        if alarms:
            reasons.append(
                'post-merge conflation alarms on survivor '
                f'{survivor.pk}: {sorted(alarms)}'
            )
        # Different-sellers gate (documented approximation of the
        # COEXISTING alarm shape): a merge that puts >=2
        # same-deal-type ads from DIFFERENT sellers on one
        # property may be fusing two units that two agencies each
        # listed once.
        same_deal = defaultdict(list)
        for ad in linked_post:
            same_deal[type(ad)].append(ad)
        for model, ads in same_deal.items():
            if len(ads) < 2:
                continue
            if len(
                Command._seller_groups(ads)
            ) >= 2:
                reasons.append(
                    f'post-merge {model.__name__} ads come from '
                    '>=2 different sellers'
                )
        return reasons

    # --- merge reporting ------------------------------------------

    def _report_merge(self, kind, counts, review, approved):
        mode = 'DRY-RUN (nothing written)' if self.dry_run \
            else 'WRITE'
        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(f'{kind} — {mode} (merge-same-block)')
        self.stdout.write(f'{"=" * 60}')
        self.stdout.write(
            f'  Clusters found:       {counts["found"]}'
        )
        if approved is not None:
            self.stdout.write(
                f'  Not in --pks:         '
                f'{counts["not_approved"]}'
            )
        verb = 'Would merge' if self.dry_run else 'Merged'
        self.stdout.write(
            f'  {verb}:            {counts["merged"]}'
        )
        verb2 = 'Would move' if self.dry_run else 'Moved'
        self.stdout.write(
            f'  Ads {verb2.lower()}:      '
            f'{counts["ads_moved"]}'
        )
        self.stdout.write(
            f'  Victim props deleted: '
            f'{counts["victims_deleted"]}'
        )
        self.stdout.write(
            f'  Victim props kept:    '
            f'{counts["victims_kept"]}'
        )
        self.stdout.write(
            f'  Skipped (review):     '
            f'{counts["skipped_review"]}'
        )
        self.stdout.write(
            f'  Skipped (stale):      '
            f'{counts["skipped_stale"]}'
        )
        if review:
            self.stdout.write('  Review list (not merged):')
            for member_pks, reasons in review:
                self.stdout.write(
                    f'    cluster {list(member_pks)}: '
                    f'{"; ".join(reasons)}'
                )
            logger.info(
                'merge-same-block review list (%s): %s',
                kind, review,
            )

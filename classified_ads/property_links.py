"""Shared helpers for ad <-> property link bookkeeping and repair.

Factored out of ``link_ads_to_properties``, ``admin.py`` and
``audit_property_links`` so the read-only audit and the write-side
``relink_property_ads`` command share one definition of the
TWIN_DIVERGED queue and one emptied-property cleanup path
(conflation plan §3c/§3d).
"""
import logging
from collections import defaultdict

logger = logging.getLogger('classified_ads')

# Match statuses that count as "linked" for audit/relink purposes.
LINKED_STATUSES = ('auto', 'manual')


def linked_by_ad_id(ad_model):
    """``ad_id -> property_id`` for rows with a live property link.

    ``all_objects`` deliberately — hidden and misclassified rows
    still carry their link and still count for twin bookkeeping.
    """
    return dict(
        ad_model.all_objects.filter(
            property_id__isnull=False,
            property_match_status__in=LINKED_STATUSES,
        ).values_list('ad_id', 'property_id')
    )


def diverged_twin_pairs(rent_model, sale_model):
    """Cross-deal ad_id pairs linked to different properties.

    Returns ``[(ad_id, rent_property_id, sale_property_id), ...]``
    sorted by ad_id — the TWIN_DIVERGED queue that
    ``audit_property_links`` reports and
    ``relink_property_ads --twin-fix`` drains. Both rows must hold
    an auto/manual link (the sale side is the move target).
    """
    rent_links = linked_by_ad_id(rent_model)
    sale_links = linked_by_ad_id(sale_model)
    return [
        (ad_id, rent_links[ad_id], sale_links[ad_id])
        for ad_id in sorted(set(rent_links) & set(sale_links))
        if rent_links[ad_id] != sale_links[ad_id]
    ]


def twin_fanout_props(pairs):
    """Prop pks whose twins fan out to >=2 distinct properties.

    The decisive mega-property conflation signature (conflation
    plan §3c): one property whose cross-deal twins live on two or
    more different properties means the property is absorbing
    unrelated units.
    """
    targets = defaultdict(set)
    for _, r_prop, s_prop in pairs:
        targets[r_prop].add(s_prop)
        targets[s_prop].add(r_prop)
    return {
        pk for pk, tset in targets.items() if len(tset) >= 2
    }


def delete_if_orphan(prop):
    """Drop a property that no longer has any linked ads.

    ``all_objects`` — hidden/misclassified ads still count as
    linked, otherwise their FK would be NULLed while their match
    status still says linked. Returns True when deleted.
    """
    linked = (
        prop.rent_ads.model.all_objects
        .filter(property=prop).exists()
        or prop.sale_ads.model.all_objects
        .filter(property=prop).exists()
    )
    if linked:
        return False
    prop.delete()
    return True


def refresh_or_delete_vacated(prop, ad, dry_run=False):
    """Refresh or drop ``prop`` after ``ad`` moved off it.

    ``ad`` is discarded from the in-memory linked-ad list (a fresh
    list is cached from the DB when absent) so the dry-run path —
    where the FK move was never saved — sees the same post-move
    state as the write path. An emptied property is deleted (same
    semantics as the admin unlink action) so it can't attract
    false matches. Returns 'refreshed' or 'deleted'.
    """
    if getattr(prop, '_linked_ads_cache', None) is None:
        prop._linked_ads_cache = prop.linked_ads()
    prop.discard_linked_ad(ad)
    if prop.linked_ads():
        prop.refresh_from_ads(save=not dry_run)
        return 'refreshed'
    if not dry_run:
        prop.delete()
    return 'deleted'

"""Score-based matching of classified ads to canonical properties.

Used by the ``link_ads_to_properties`` management command; see
``docs/plans/property_conflation_prevention_plan.md`` §3a for the
conflation alarms that demote ``auto`` decisions to ``candidate``.
"""
import logging
import re
from itertools import combinations

from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger('classified_ads')

AUTO_THRESHOLD = 0.8
CANDIDATE_THRESHOLD = 0.45
TEMPORAL_GAP_DAYS = 14
SIZE_HARD_REJECT_PCT = 0.15
COMMENT_SIMILARITY_MIN = 0.8
# Same-deal linked ads whose seen-windows overlap >= N days are a
# batch-absorption signature (mirrors audit_property_links).
OVERLAP_MIN_DAYS = 2

# Conflation alarm names — aligned with the audit_property_links flag
# taxonomy (TWIN_DIVERGED is produced by the audit, not the matcher).
ALARM_APTNO_CONFLICT = 'APTNO_CONFLICT'
ALARM_COEXISTING = 'COEXISTING'
ALARM_FLOOR_CONFLICT = 'FLOOR_CONFLICT'
ALARM_DEGENERATE_BLOCK = 'DEGENERATE_BLOCK'
ALARM_MULTI_CANDIDATE = 'MULTI_CANDIDATE'

# Trailing street designators stripped when normalizing street names.
_STREET_DESIGNATORS = (
    'iela', 'ielas', 'ielā', 'ielu',
    'bulvāris', 'bulvāra', 'bulvāri', 'bulvārī', 'bulv',
    'ceļš', 'cela', 'ceļa', 'ceļu',
    'šoseja', 'šosejas',
    'laukums', 'laukuma', 'laukumā', 'lauk',
    'prospekts', 'prospekta',
    'gatve', 'gatves',
    'dambis', 'dambja',
    'līnija', 'līnijas',
)
_SUFFIX_RE = re.compile(
    r'\s+(?:' + '|'.join(_STREET_DESIGNATORS) + r')\.?$'
)
# Leading initials such as "A. " in "A. Čaka iela".
_INITIALS_RE = re.compile(r'^(?:[a-zāčēģīķļņšūž]\.\s*)+')

_WS_RE = re.compile(r'\s+')

# ss.com fuses house+apartment numbers into one token ("12-3" = house
# 12, apt 3). Only the pure digits-digits shape is split — corpus
# suffixes like "5k-1" must not be touched (conflation plan §3a.4).
_FUSED_STREET_NO_RE = re.compile(r'^(\d+)-(\d+)$')

# Apartment numbers mentioned in comments, e.g. "Dzīvoklis Nr. 49".
# A marker word is required — a bare number after "dzīvoklis" is too
# often a floor or room count (conflation plan §3b).
_APT_NO_PATTERNS = (
    re.compile(
        r'dz[īi]vok\w*\.?\s+(?:nr\.?|numurs|#)\s*[:.]?\s*(\d{1,4})',
        re.IGNORECASE,
    ),
    # Windowed form: "dzīvokli ... Nr. 7" within ~30 chars. The gap
    # must be "māja"-free — "dzīvokļu māja Nr. 5" is the building's
    # number, not a unit.
    re.compile(
        r'dz[īi]vok\w*(?:(?!māj)[^\n.]){0,30}?'
        r'\bnr\.?\s*[:.]?\s*(\d{1,4})',
        re.IGNORECASE,
    ),
    re.compile(r'\bdz\.\s*nr\.?\s*(\d{1,4})', re.IGNORECASE),
    # "dz. 12" without nr — guarded against room counts
    # ("dz. 3 istabas") and floor shorthand ("dz. 3. stāvā",
    # "dz. 3 st.").
    re.compile(
        r'\bdz\.?\s*(\d{1,4})(?!\d)(?!\s*ist)'
        r'(?!\s*\.?\s*st(?:\b|[āa]))',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:flat|apartment)\s+(?:nr\.?|no\.?|#)\s*(\d{1,4})',
        re.IGNORECASE,
    ),
    # English bare forms: "apt. 7" / "flat 9".
    re.compile(r'\b(?:apt|flat)\.?\s*(\d{1,4})\b', re.IGNORECASE),
    # Russian "кв. 12" — guarded against "кв. N м" square metres and
    # "кв. N-комнатная" / "кв. N комн." room counts.
    re.compile(
        r'\bкв\.?\s*(\d{1,4})(?!\d)(?!\s*м)(?![\s-]*комн)',
        re.IGNORECASE,
    ),
)

_WORD_RE = re.compile(r'\w+')


def normalize_street_name(name):
    """Lowercase, collapse whitespace, drop initials and designators.

    "A. Čaka iela" and "Čaka" both normalize to "čaka".
    """
    s = _WS_RE.sub(' ', (name or '').strip().lower())
    s = _INITIALS_RE.sub('', s)
    return _SUFFIX_RE.sub('', s).strip()


def normalize_street_no(no):
    """Canonical street number for block keys and comparisons.

    A fused ``N-M`` house-apt token ("12-3") normalizes to its house
    part ("12"); the suffix is recovered as a match-time apartment
    number by :func:`_ad_apartment_no`.
    """
    s = _WS_RE.sub(' ', (no or '').strip().lower())
    match = _FUSED_STREET_NO_RE.match(s)
    if match:
        return match.group(1)
    return s


def normalize_apartment_no(no):
    s = (no or '').strip().lower()
    if s.isdigit():
        return str(int(s))
    return s


def fused_street_no_apt(street_no):
    """The ``M`` suffix of a fused ``N-M`` street_no token, else ''.

    ss.com writes house+unit as one token ("12-3"); the suffix is
    the apartment number (conflation plan §3a.4).
    """
    match = _FUSED_STREET_NO_RE.match(
        (street_no or '').strip().lower()
    )
    if match:
        return str(int(match.group(2)))
    return ''


def extract_apartment_no(comment):
    """Pull an apartment number out of ad comment text, if present."""
    if not comment:
        return ''
    for pattern in _APT_NO_PATTERNS:
        match = pattern.search(comment)
        if match:
            return str(int(match.group(1)))
    return ''


def _ad_apartment_no(ad):
    """Stored apartment number, or one recovered at match time.

    Falls back to the comment text, then to the ``M`` suffix of a
    fused ``N-M`` street_no ("12-3" → apt "3") — a candidate value
    only; the stored fields are never rewritten.
    """
    stored = normalize_apartment_no(getattr(ad, 'apartment_no', ''))
    if stored:
        return stored
    extracted = extract_apartment_no(getattr(ad, 'comment', ''))
    if extracted:
        return extracted
    return fused_street_no_apt(getattr(ad, 'street_no', ''))


def _property_apartment_nos(prop):
    """All apartment numbers associated with a property."""
    nos = set()
    own = normalize_apartment_no(getattr(prop, 'apartment_no', ''))
    if own:
        nos.add(own)
    for ad in prop.iter_linked_ads():
        ad_no = _ad_apartment_no(ad)
        if ad_no:
            nos.add(ad_no)
    return nos


def _size_too_different(a, b):
    if not a or not b:
        return False
    return abs(a - b) / max(a, b) > SIZE_HARD_REJECT_PCT


def _size_score(a, b):
    if not a or not b:
        return 0.0
    diff = abs(a - b)
    if diff <= 1.0:
        return 0.25
    rel = diff / max(a, b)
    if rel <= 0.03:
        return 0.18
    if rel <= 0.10:
        return 0.08
    return 0.0


def _hard_reject(ad, prop, ad_no, prop_nos):
    if prop.rooms != ad.rooms:
        return True
    if _size_too_different(ad.size, prop.size):
        return True
    if ad_no and prop_nos and ad_no not in prop_nos:
        return True
    return False


def _seller_or_none(ad):
    """ad.seller, tolerating a dangling seller_id."""
    try:
        return ad.seller
    except ObjectDoesNotExist:
        return None


def _same_seller_in(ad, linked):
    if not getattr(ad, 'seller_id', None):
        return False
    ad_seller = _seller_or_none(ad)
    for other in linked:
        if not getattr(other, 'seller_id', None):
            continue
        if other.seller_id == ad.seller_id:
            return True
        if ad_seller is None:
            continue
        other_seller = _seller_or_none(other)
        if other_seller and (
            (other_seller.phone and other_seller.phone == ad_seller.phone)
            or (
                other_seller.contact_id
                and other_seller.contact_id == ad_seller.contact_id
            )
        ):
            return True
    return False


def _tokens(text):
    return set(_WORD_RE.findall((text or '').lower()))


def _comment_similar(ad, linked):
    tokens = _tokens(getattr(ad, 'comment', ''))
    if not tokens:
        return False
    for other in linked:
        other_tokens = _tokens(getattr(other, 'comment', ''))
        if not other_tokens:
            continue
        union = tokens | other_tokens
        if len(tokens & other_tokens) / len(union) >= (
            COMMENT_SIMILARITY_MIN
        ):
            return True
    return False


def _temporally_adjacent(ad, prop):
    """+signal when ad.first_seen is just after prop.last_seen.

    The classic delete-and-repost signature: an ad disappears and an
    identical one is created within a couple of weeks.
    """
    if not ad.first_seen or not prop.last_seen:
        return False
    gap_days = (ad.first_seen - prop.last_seen).total_seconds() / 86400
    return -1 <= gap_days <= TEMPORAL_GAP_DAYS


def _same_seller_pair(a, b):
    """Do two ads share a seller (id, phone or contact_id)?"""
    if a.seller_id and a.seller_id == b.seller_id:
        return True
    sa, sb = _seller_or_none(a), _seller_or_none(b)
    if sa and sb:
        return bool(
            (sa.phone and sa.phone == sb.phone)
            or (sa.contact_id and sa.contact_id == sb.contact_id)
        )
    return False


def _seen_window(ad):
    """(first_seen, last_seen) as dates, or None if undated."""
    first = getattr(ad, 'first_seen', None)
    if first is None:
        return None
    last = getattr(ad, 'last_seen', None) or first
    return first.date(), last.date()


def _has_coexisting_pair(ads):
    """Same-seller ad pair whose seen-windows overlap >= 2 days."""
    for a, b in combinations(ads, 2):
        if not _same_seller_pair(a, b):
            continue
        wa, wb = _seen_window(a), _seen_window(b)
        if not wa or not wb:
            continue
        overlap = (min(wa[1], wb[1]) - max(wa[0], wb[0])).days
        if overlap >= OVERLAP_MIN_DAYS:
            return True
    return False


def conflation_alarms(ad, prop, prop_nos, linked):
    """Conflation signatures for linking ``ad`` onto ``prop``.

    Returns a set of alarm names using the audit_property_links flag
    taxonomy. Any alarm demotes an ``auto`` decision to ``candidate``
    — the evidence-shaped alarms (degenerate block, multiple
    candidates) are added by :func:`match_property` only when the ad
    lacks decisive evidence (apt_no match or a linked twin).
    """
    alarms = set()
    if len(prop_nos) >= 2:
        # Property already holds multiple unit numbers.
        alarms.add(ALARM_APTNO_CONFLICT)
    same_deal = [a for a in linked if type(a) is type(ad)]
    if _has_coexisting_pair(same_deal):
        # Batch-absorption signature: two same-seller ads of the same
        # deal type already coexist on one property.
        alarms.add(ALARM_COEXISTING)
    floor_attr = 'floor' if hasattr(prop, 'floor') else 'floors'
    floors = {getattr(a, floor_attr, None) for a in linked}
    floors.discard(None)
    ad_floor = getattr(ad, floor_attr, None)
    if len(floors) > 1 or (
        floors and ad_floor is not None and floors != {ad_floor}
    ):
        alarms.add(ALARM_FLOOR_CONFLICT)
    return alarms


def _score_candidate(ad, prop, ad_no, prop_nos, linked):
    score = 0.0
    if ad_no and ad_no in prop_nos:
        score += 0.40
    if _same_seller_in(ad, linked):
        score += 0.30
    score += _size_score(ad.size, prop.size)
    ad_floor = getattr(ad, 'floor', None)
    if ad_floor is not None and ad_floor == getattr(
        prop, 'floor', None
    ):
        score += 0.15
    ad_max_floor = getattr(ad, 'max_floor', None)
    if ad_max_floor is not None and ad_max_floor == getattr(
        prop, 'max_floor', None
    ):
        score += 0.05
    if getattr(ad, 'floors', None) is not None:
        if ad.floors == getattr(prop, 'floors', None):
            score += 0.15
    if (
        getattr(ad, 'project_id', None)
        and ad.project_id == getattr(prop, 'project_id', None)
    ):
        score += 0.10
    ad_land = getattr(ad, 'land_area_sqm', None)
    prop_land = getattr(prop, 'land_area_sqm', None)
    if ad_land is not None and ad_land == prop_land:
        score += 0.20
    if _comment_similar(ad, linked):
        score += 0.15
    if _temporally_adjacent(ad, prop):
        score += 0.10
    return score


def match_property(ad, candidates,
                   auto_threshold=AUTO_THRESHOLD,
                   candidate_threshold=CANDIDATE_THRESHOLD,
                   twin_prop_ids=None):
    """Match ``ad`` against blocked ``candidates`` (same building).

    ``candidates`` is an iterable of property objects already narrowed
    to the ad's block (district + street number) by the caller.
    ``twin_prop_ids`` holds the pks of properties the ad's cross-deal
    twin is linked to — membership is decisive evidence alongside an
    apartment-number match.

    Returns ``(property_or_None, score, decision)`` where decision is
    'auto' (link now), 'candidate' (review queue) or 'new' (create a
    fresh property — also when no candidates survive). Conflation
    alarms cap an 'auto' decision at 'candidate' — they demote, they
    never promote a sub-threshold score.
    """
    ad_street = normalize_street_name(ad.street_name)
    ad_street_no = normalize_street_no(ad.street_no)
    ad_no = _ad_apartment_no(ad)
    twin_ids = set(twin_prop_ids or ())

    survivors = []
    for prop in candidates:
        if normalize_street_name(prop.street_name) != ad_street:
            continue
        if normalize_street_no(prop.street_no) != ad_street_no:
            continue
        prop_nos = _property_apartment_nos(prop)
        if _hard_reject(ad, prop, ad_no, prop_nos):
            continue
        linked = list(prop.iter_linked_ads())
        score = _score_candidate(ad, prop, ad_no, prop_nos, linked)
        survivors.append((prop, score, prop_nos, linked))

    if not survivors:
        return None, 0.0, 'new'

    # Decisive evidence: the ad's apartment number already lives on
    # the property, or the ad's cross-deal twin is linked there.
    # Evaluate it across all survivors — when several survive, the
    # property holding the evidence wins over a higher-scoring
    # lookalike.
    decisive_pool = [
        s for s in survivors
        if (ad_no and ad_no in s[2]) or s[0].pk in twin_ids
    ]
    decisive = bool(decisive_pool)
    prop, best_score, prop_nos, linked = max(
        decisive_pool or survivors, key=lambda s: s[1]
    )
    alarms = conflation_alarms(ad, prop, prop_nos, linked)
    if not ad_street_no and not decisive:
        # Settlement-level block (street_no == ''): the street name
        # is a town, so the bucket spans the whole district — only
        # decisive evidence may auto-link here.
        alarms.add(ALARM_DEGENERATE_BLOCK)
    if len(survivors) > 1 and not decisive:
        # The score alone is choosing between lookalike properties.
        alarms.add(ALARM_MULTI_CANDIDATE)
    if alarms:
        logger.info(
            'conflation alarms for ad %s -> prop %s: %s',
            getattr(ad, 'ad_id', '?'), prop.pk, sorted(alarms),
        )
        if best_score >= candidate_threshold:
            return prop, best_score, 'candidate'
        return None, best_score, 'new'

    if best_score >= auto_threshold:
        return prop, best_score, 'auto'
    if best_score >= candidate_threshold:
        return prop, best_score, 'candidate'
    return None, best_score, 'new'

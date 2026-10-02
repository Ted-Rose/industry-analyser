"""Score-based matching of classified ads to canonical properties.

Used by the ``link_ads_to_properties`` management command; see
``docs/property_linking_plan.md`` for the full design.
"""
import logging
import re

from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger('classified_ads')

AUTO_THRESHOLD = 0.8
CANDIDATE_THRESHOLD = 0.45
TEMPORAL_GAP_DAYS = 14
SIZE_HARD_REJECT_PCT = 0.15
COMMENT_SIMILARITY_MIN = 0.8

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

# Apartment numbers mentioned in comments, e.g. "Dzīvoklis Nr. 49".
# The marker word is required — a bare number after "dzīvoklis" is too
# often a floor or room count.
_APT_NO_PATTERNS = (
    re.compile(
        r'dz[īi]vok\w*\.?\s+(?:nr\.?|numurs|#)\s*[:.]?\s*(\d{1,4})',
        re.IGNORECASE,
    ),
    re.compile(r'\bdz\.\s*nr\.?\s*(\d{1,4})', re.IGNORECASE),
    re.compile(
        r'\b(?:flat|apartment)\s+(?:nr\.?|no\.?|#)\s*(\d{1,4})',
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
    return _WS_RE.sub(' ', (no or '').strip().lower())


def normalize_apartment_no(no):
    s = (no or '').strip().lower()
    if s.isdigit():
        return str(int(s))
    return s


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
    """Stored apartment number, or one extracted from the comment."""
    return normalize_apartment_no(
        getattr(ad, 'apartment_no', '') or extract_apartment_no(
            getattr(ad, 'comment', '')
        )
    )


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
                   candidate_threshold=CANDIDATE_THRESHOLD):
    """Match ``ad`` against blocked ``candidates`` (same building).

    ``candidates`` is an iterable of property objects already narrowed
    to the ad's block (district + street number) by the caller.
    Returns ``(property_or_None, score, decision)`` where decision is
    'auto' (link now), 'candidate' (review queue) or 'new' (create a
    fresh property — also when no candidates survive).
    """
    ad_street = normalize_street_name(ad.street_name)
    ad_street_no = normalize_street_no(ad.street_no)
    ad_no = _ad_apartment_no(ad)

    best_prop, best_score = None, 0.0
    for prop in candidates:
        if normalize_street_name(prop.street_name) != ad_street:
            continue
        if normalize_street_no(prop.street_no) != ad_street_no:
            continue
        prop_nos = _property_apartment_nos(prop)
        if _hard_reject(ad, prop, ad_no, prop_nos):
            continue
        score = _score_candidate(
            ad, prop, ad_no, prop_nos, list(prop.iter_linked_ads())
        )
        if score > best_score:
            best_prop, best_score = prop, score

    if best_prop is None:
        return None, 0.0, 'new'
    if best_score >= auto_threshold:
        return best_prop, best_score, 'auto'
    if best_score >= candidate_threshold:
        return best_prop, best_score, 'candidate'
    return None, best_score, 'new'

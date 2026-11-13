"""Detection of non-monthly-rate and partial-unit rental ads.

ss.com rent listings can carry a per-day or per-week price in the
listing price cells ("35 €/day", "25 €/dienā"). The scrapers'
``_clean_price`` monthlyizes them (day x30, week x4) but drops the
marker, so ``monthly_price`` mixes real monthly rents with
converted short-stay rates and rent medians get polluted.
``detect_rate_period`` runs at ingest on the raw cell text, right
next to ``_clean_price``, and the result is stored on the ad's
``rate_period`` ('day'/'week'/'month'; '' = unknown — every row
predating the flag).

A second, unrelated data smell is ads renting only a room in a
flat or part of a house — a different product than a whole-unit
let — detected from comment keywords (Latvian + Russian), in the
same style as ``sale_flags.py``.

The post-hoc helpers backfill flags on pre-existing rows where
the raw price text is gone:

- apartments: the ratio
  ``monthly_price / (monthly_price_per_sqm * size)`` is ~1 for a
  real monthly ad but ~30/~4 (or the inverse) when exactly one of
  the two price cells was a converted daily/weekly rate;
- houses: ``monthly_price_per_sqm`` is derived (price / size), so
  the ratio trick is impossible — an implausibly high stored
  per-m² rent is the residue of a x30 daily rate instead;
- both: short-stay vocabulary in the comment.

Comment patterns were rewritten after the first backfill run
over-flagged ordinary ads (see PR #55): loose substrings like
``dien`` match everyday words — ``ikdienas`` (everyday),
``pusdienas`` (lunch), ``mūsdienām``, ``brīvdienās``, weekday
names, ``diena-nakts žalūzijas``, ``naktsgaldiņi`` (bedside
tables), ``diennakts apsardze`` (24h security) — and bare
``комнат`` matches ``2-комнатная квартира`` (an ordinary
2-room flat, ~35% of all apt ads). Every pattern below is
therefore
either anchored to a rent/price context (``par nakti``,
``cena … dienā``, ``eur/nedēļā``, ``minimālais termiņš N
naktis``) or to a whole-word that only appears in rate/room-share
context (``diennakt``, ``сутки``, ``посуточно``, ``per night``).
Verified against prod comments: ~11% of clean apt rents and ~28%
of clean house rents carry a short-stay signal — in line with
the manual review's ~10%/22% estimates.
"""
import re

# Rate-cell markers — intentionally the exact sets the scrapers'
# _clean_price converts, so rate_period != 'month' means the
# stored price was monthlyized.
DAY_PRICE_MARKERS = ('/day', '/dienā')
WEEK_PRICE_MARKERS = ('/week', '/nedēļā')

SHORT_STAY_PERIODS = ('day', 'week')

# price/rate context words — word-bounded so 'centrā' (centre),
# 'samaksa' (payment) and 'parks' don't count
_PRICE_WORDS = (
    r'(?:\beur\w*|€|\bcena\b|\bcenu\b|\bcenas\b|\bcenām\b|'
    r'\bmaksa\b|\bmaksā\b|\bmaksu\b|\bmaksājum\w*|\bprice\b)'
)
# Inflected Latvian day/night words that only appear in rate
# context — nominative 'diena'/'nakts' alone is excluded (matches
# 'dienas ritms', 'nakts skats', 'diena-nakts žalūzijas').
_DAY_WORDS = (
    r'(?:diennakt\w*|dienā|dienām|dienas|nakts|nakti|naktis|'
    r'naktī|naktīm)'
)

# 'diennakts apsardze/recepcija/…' is 24h building service, not a
# rate — stripped before the 'diennakt' check.
_DIENNAKT_SERVICE = re.compile(
    r'diennakts?\s+(?:apsardz\w*|recep\w*|reseps\w*|recepš\w*|'
    r'concierge|apkalp\w*|droš\w*|dežur\w*|vies\w*|admin\w*|'
    r'pārvaldn\w*|apsaimn\w*)'
)

DAY_COMMENT_PATTERNS = tuple(re.compile(p) for p in (
    # 'par dienu/dienām/nakti/naktīm' — 'par' = priced per period
    r'par\s+(?:dienām|dienu|dienas|diennakt\w*|nakti|naktis|'
    r'naktī|naktīm|nakts)\b',
    # 'uz dienu/nakti' — let for a day/night ('uz dienvid*' is
    # 'south', excluded by the bounded word list)
    r'uz\s+(?:dienām|dienu|dienas|diennakt\w*|nakti|naktīm|'
    r'naktis)\b',
    r'pa\s+(?:dienām|diennakt\w*)\b',
    # '2 naktis', '5 diennaktis', '40 dienā' — minimum-stay
    # and per-day wording anchored on a number
    r'\d+\s*(?:nakts|nakti|naktis|naktīm|dienā|dienām|dienu|'
    r'dienas|diennakt\w*)\b',
    r'no\s+\d+\s*(?:dienām|dienas|naktīm|naktis|diennakt\w*)',
    # price within ~20 chars of a day/night word, either order
    _PRICE_WORDS + r'[^.]{0,20}\b' + _DAY_WORDS + r'\b',
    r'\b' + _DAY_WORDS + r'\b[^.]{0,15}' + _PRICE_WORDS,
    # Russian / English — whole words, no adjective FPs
    r'сутк|посуточн|\bночь\b|\bночи\b|ночей',
    r'per\s+night|per\s+day|\ba\s+night\b|nightly',
    # 'nakšņo' — 'spend the night' verb
    r'nakšņo\w*',
))

# 'nedēļ' needs the same price/rent context — bare 'nedēļas'
# matches 'nedēļas nogale' (weekend) in lifestyle copy.
WEEK_COMMENT_PATTERNS = tuple(re.compile(p) for p in (
    r'(?:\beur\w*|€|\bcena\b|\bcenu\b|\bcenas\b|\bmaks\w*|'
    r'\bpar\b|\buz\b)[^.]{0,20}\bnedēļ\w*',
    r'\bnedēļ\w*[^.]{0,15}' + _PRICE_WORDS,
    r'(?:за|в|по|на)\s+недел\w*|\d+\s*недел\w*|'
    r'недел\w*\s*(?:аренд|стоим|цена|eur|€)',
    r'per\s+week|weekly',
))

# Short-term vocabulary that doesn't pin down the rate period —
# counted as a daily-rate product (nightly lets dominate ss.com
# short stays; see flag_short_stay_ads). 'sezon*' was dropped to
# 'uz sezonu'/'īrē sezonu' only: 'sezonā/sezonas' is almost
# always the *heating* season in utility boilerplate.
GENERIC_SHORT_STAY_PATTERNS = tuple(re.compile(p) for p in (
    r'īstermiņ',
    r'brīvdienu\s+(?:māj|dzīvokl|apartam|vies|nometn|dom)',
    r'naktsmītn|nakts\s+mītn',
    # 'minimālais termiņš/uzturēšanās ilgums — N naktis'
    r'minimāl\w*[^.]{0,60}\b(?:nakt|diennakt|\d+\s*dien)',
    r'uz\s+(?:vasaras\s+|ziemas\s+)?sezonu|īr\w*\s+sezonu',
    r'short[-\s]stay|short[-\s]term\s+rent',
))

# Room-share / partial-unit vocabulary. Every phrase requires the
# share context: bare 'istabu' matches "3 istabu dzīvoklis" (an
# ordinary 3-room flat, genitive rooms) and bare 'комнат' matches
# 'N-комнатная квартира' — both are whole-unit lets.
ROOM_SHARE_PATTERNS = tuple(re.compile(p) for p in (
    # Latvian — 'istabu/istaba' in a locative place: a room in a
    # flat / house / shared flat ('N istabu dzīvoklī' where N is
    # a numeral is excluded in _lv_room_share — it's the flat's
    # room count, e.g. "īrei 1 istabas dzīvoklī" = whole 1-room
    # flat)
    r'\bistab\w*\s+(?:mājā|privātmājā|kopdzīvoklī)\b',
    # room + flat-size enumeration: 'istabu, 4 istabu
    # dzīvoklī' / 'istabu trīs istabu dzīvoklī' — a room
    # offered inside an N-room flat
    r'\bistabu\s*[,-]?\s*(?:\d+|vien\w*|div\w*|trīs|četr\w*|'
    r'piec\w*)\s+istabu\s+dzīvoklī\b',
    r'\bkopdzīvokl\w*|\bkopmītņ\w*|komunāl\w*\s+dzīvokl\w*',
    # Latvian — part of a house; 'mājas pusi' needs rent context
    # ('logi uz mājas pusēm' = windows facing both sides)
    r'mājas\s+daļ|daļu?\s+no\s+mājas',
    r'(?:īr|nom|izīr|iznom)\w*[^.]{0,25}mājas\s+pus|'
    r'mājas\s+pus\w*[^.]{0,20}(?:īr|nom)',
    # Russian — 'комната' (room) with a share verb or person —
    # never the 'N-комнатная' adjective
    r'(?:сда|сним|аренду|подсел)\w*\s+комнат|'
    r'комнат\w*\s+(?:сда|сним)\w*',
    r'комнат\w*\s+в\s+(?:\w+\s+){0,2}'
    r'(?:квартир|доме|частном)',
    r'комнат\w*\s+(?:девушк|парн|студент|одному|одного|'
    r'одной)',
    r'част[ьи]\s+дома|полдома|пол\s+дома',
    # English
    r'room\s+(?:for|to)\s+rent|'
    r'room\s+in\s+(?:a\s+|an\s+)?(?:flat|apartment|house|shared)|'
    r'shared\s+(?:flat|apartment|house)|private\s+room',
    # 'istaba īrei' — 'īrei'/'īrēj'/'tiek izīrēta' after the room
    # word; 'guļamistabām īrei' (a flat *with* bedrooms) is
    # excluded by the \b
    r'\bistab\w*\s+īrei',
    r'\bistab\w*\s+(?:tiek|netiek|tiks|ir|būs)?\s*'
    r'(?:iz?īrē\w+|iznomā\w+)',
    # room offered to a person: 'istabu studentei/vīrietim'
    r'\bistab\w*\s+(?:student\w*|vīriet\w*|meiten\w*|jaunieš\w*|'
    r'sievet\w*|pensionār\w*|strādniek\w*)',
    r'koplietošanas\s+istab',
    # a rented bed slot — 'спальные места'/'gultas vietas' alone
    # means "sleeps N" (whole let), so only the bed-slot phrasing
    r'кроват\w*\s*мест|койко\s*мест',
))

# Latvian room-share: 'istab*' tokens describing an offered room,
# not the flat's room count. 'izīrē istabu', 'izīrēju 1 istabu,
# 4 istabu dzīvoklī', 'istaba tiek izīrēta', 'istabu īrējam',
# 'istabu trīs istabu dzīvoklī' are shares; '2 istabu dzīvokli',
# 'istabu studio tipa dzīvoklis', 'istabu skaits: 3',
# 'dzīvokli, istabas izolētas' are flat-size descriptors.
_ISTAB_TOKEN = re.compile(r'\bistab\w*')
_ISTAB_NUM_PREV = re.compile(
    r'(?:vien\w*|div\w*|trīs|četr\w*|piec\w*|seš\w*|septiņ\w*|'
    r'astoņ\w*|deviņ\w*|\d+[-–]?|[-–])\s*$'
)
_ISTAB_FLAT_PREV = re.compile(r'dzīvokl\w*[,\s]*$')
_ISTAB_SKAIT_AFTER = re.compile(r'\s+skait')
# adjective chain ending in a non-locative 'dzīvokl*' — locative
# 'dzīvoklī' means the flat is the *location* = share context
_ISTAB_SIZE_AFTER = re.compile(r'(?:[\w\-]+\s+){0,3}dzīvokl(?!ī)\w*')
_ISTAB_SHARE_VERB = re.compile(
    r'(?:iz?īrē\w*|iznomā\w*|nomā\w*|piedāvā\w*)[^.]{0,20}$'
)


def _lv_room_share(low):
    """True when a Latvian 'istab*' token is an offered room."""
    for m in _ISTAB_TOKEN.finditer(low):
        prev = low[max(0, m.start() - 20):m.start()]
        if _ISTAB_NUM_PREV.search(prev):
            continue  # '2 istabu', 'trīs istabu' — flat's rooms
        if _ISTAB_FLAT_PREV.search(prev):
            continue  # 'dzīvokli, istabas' — rooms of the flat
        nxt = low[m.end():]
        if _ISTAB_SKAIT_AFTER.match(nxt):
            continue  # 'istabu skaits' — room count
        if _ISTAB_SIZE_AFTER.match(nxt):
            continue  # 'istabu studio tipa dzīvoklis' — size
        # an offered room: share verb within 20 chars before it,
        # or a locative place right after it
        if _ISTAB_SHARE_VERB.search(prev):
            return True
        if re.match(
                r'\s*(?:\w+\s+){0,3}dzīvoklī\b', nxt):
            return True
    return False


# Houses: stored monthly_price_per_sqm above this is the residue
# of a daily-rate conversion — a 100 m² house at €50/day stores
# ~15 €/m²/month; real Latvian house rents sit at ~3-10 €/m².
HOUSE_SHORT_STAY_PPSQM = 15.0

# Ratio bands for the apartment consistency check: stored
# monthly_price / (monthly_price_per_sqm * size) sits at ~1 for
# real monthly ads and at the conversion factor (or its inverse)
# when the two listing cells disagreed on the period.
_RATIO_TARGETS = (
    ('day', 30.0),
    ('week', 4.0),
)
_RATIO_TOLERANCE = 0.15


def detect_rate_period(*price_texts):
    """Rate period declared by raw price-cell text.

    Returns 'day'/'week' when a period marker the scraper's
    ``_clean_price`` monthlyizes is present in ANY price cell
    (ss.com may mark either or both), else 'month'.
    """
    for text in price_texts:
        low = str(text).lower()
        if any(m in low for m in DAY_PRICE_MARKERS):
            return 'day'
        if any(m in low for m in WEEK_PRICE_MARKERS):
            return 'week'
    return 'month'


def is_room_share(comment):
    """True when the comment advertises a room / part of a unit."""
    low = (comment or '').lower()
    if not low:
        return False
    if _lv_room_share(low):
        return True
    return any(rx.search(low) for rx in ROOM_SHARE_PATTERNS)


def comment_rate_period(comment):
    """'day'/'week' when the comment names the rate period, else ''.

    Generic short-term vocabulary is deliberately not a period
    signal — ``has_short_stay_comment`` covers it.
    """
    low = (comment or '').lower()
    if not low:
        return ''
    # 'diennakts' in a service context (24h security/reception)
    # is stripped before looking for rate wording
    cleaned = _DIENNAKT_SERVICE.sub(' ', low)
    if 'diennakt' in cleaned:
        return 'day'
    if any(rx.search(low) for rx in DAY_COMMENT_PATTERNS):
        return 'day'
    if any(rx.search(low) for rx in WEEK_COMMENT_PATTERNS):
        return 'week'
    return ''


def has_short_stay_comment(comment):
    """True on any short-stay vocabulary, period-pinned or not."""
    low = (comment or '').lower()
    if not low:
        return False
    if comment_rate_period(low):
        return True
    return any(rx.search(low) for rx in GENERIC_SHORT_STAY_PATTERNS)


def _period_for_ratio(ratio):
    """'day'/'week' when the price-cells-disagree ratio hits a
    conversion band (or its inverse), else ''."""
    if ratio <= 0:
        return ''
    for period, target in _RATIO_TARGETS:
        lo = target * (1 - _RATIO_TOLERANCE)
        hi = target * (1 + _RATIO_TOLERANCE)
        if lo <= ratio <= hi or lo <= 1.0 / ratio <= hi:
            return period
    return ''


def apartment_ratio_period(monthly_price, monthly_price_per_sqm,
                           size):
    """'day'/'week' from the two-cell consistency ratio, else ''.

    Exposed separately so the backfill command can report which
    detector flagged each row.
    """
    if monthly_price_per_sqm > 0 and size > 0:
        ratio = monthly_price / (monthly_price_per_sqm * size)
        return _period_for_ratio(ratio)
    return ''


def house_ppsqm_period(monthly_price_per_sqm):
    """'day' when stored per-m² rent implies a converted daily
    rate, else '' — the house-side numeric detector."""
    if monthly_price_per_sqm > HOUSE_SHORT_STAY_PPSQM:
        return 'day'
    return ''


def apartment_rate_period_posthoc(
        monthly_price, monthly_price_per_sqm, size, comment):
    """Best-effort rate_period for an existing ApartmentForRent row.

    Comment wording first, then the two-cell consistency ratio.
    '' means "no evidence" — the row keeps 'unknown' rather than
    being asserted monthly.
    """
    period = comment_rate_period(comment)
    if period:
        return period
    if has_short_stay_comment(comment):
        return 'day'
    return apartment_ratio_period(
        monthly_price, monthly_price_per_sqm, size)


def house_rate_period_posthoc(monthly_price_per_sqm, comment):
    """Best-effort rate_period for an existing HouseForRent row.

    monthly_price_per_sqm is derived (price / size) on houses, so
    the ratio check is impossible — an implausibly high stored
    per-m² rent is the residue of a x30 daily rate.
    """
    period = comment_rate_period(comment)
    if period:
        return period
    if has_short_stay_comment(comment):
        return 'day'
    return house_ppsqm_period(monthly_price_per_sqm)

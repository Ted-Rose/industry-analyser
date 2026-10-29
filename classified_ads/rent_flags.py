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
"""

# Rate-cell markers — intentionally the exact sets the scrapers'
# _clean_price converts, so rate_period != 'month' means the
# stored price was monthlyized.
DAY_PRICE_MARKERS = ('/day', '/dienā')
WEEK_PRICE_MARKERS = ('/week', '/nedēļā')

SHORT_STAY_PERIODS = ('day', 'week')

# Comment vocabulary indicating a non-monthly rental product.
# Split so the backfill can record the specific period where the
# wording pins it down.
DAY_COMMENT_MARKERS = (
    'dienā', 'diena', 'dienu', 'nakt',
    'сутк', 'посуточн', 'ночь',
    'per night', 'per day',
)
WEEK_COMMENT_MARKERS = (
    'nedēļ', 'недел', 'per week',
)
# Short-term vocabulary that doesn't pin down the rate period —
# counted as a daily-rate product (nightly lets dominate ss.com
# short stays; see flag_short_stay_ads).
GENERIC_SHORT_STAY_MARKERS = (
    'īstermiņ', 'sezon', 'brīvdienu',
)

# Room-share / partial-unit vocabulary. Kept conservative —
# bare 'istabu' would match "2 istabu dzīvoklis" (an ordinary
# 2-room flat), so every phrase requires the share context.
ROOM_SHARE_KEYWORDS = [
    # Latvian — a room inside a shared flat
    'istabu dzīvoklī', 'istaba dzīvoklī',
    'īrē istabu', 'īrējam istabu',
    'istabu īr', 'istabas īr',
    # Latvian — only part of a house
    'mājas daļa', 'mājas daļu', 'daļu mājas', 'daļa mājas',
    'mājas spārn', 'mājas pus', 'puse mājas', 'pusi mājas',
    # Russian — a room / part of a house
    'комнат', 'часть дома', 'части дома', 'полдома', 'пол дома',
    # English
    'room for rent', 'room to rent',
]

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
    return any(k in low for k in ROOM_SHARE_KEYWORDS)


def comment_rate_period(comment):
    """'day'/'week' when the comment names the rate period, else ''.

    Generic short-term vocabulary is deliberately not a period
    signal — ``has_short_stay_comment`` covers it.
    """
    low = (comment or '').lower()
    if not low:
        return ''
    if any(m in low for m in DAY_COMMENT_MARKERS):
        return 'day'
    if any(m in low for m in WEEK_COMMENT_MARKERS):
        return 'week'
    return ''


def has_short_stay_comment(comment):
    """True on any short-stay vocabulary, period-pinned or not."""
    low = (comment or '').lower()
    if not low:
        return False
    markers = (
        DAY_COMMENT_MARKERS
        + WEEK_COMMENT_MARKERS
        + GENERIC_SHORT_STAY_MARKERS
    )
    return any(m in low for m in markers)


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
    if monthly_price_per_sqm > 0 and size > 0:
        ratio = monthly_price / (monthly_price_per_sqm * size)
        return _period_for_ratio(ratio)
    return ''


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
    if monthly_price_per_sqm > HOUSE_SHORT_STAY_PPSQM:
        return 'day'
    return ''

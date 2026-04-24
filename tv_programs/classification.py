"""
Heuristic TV program classification from tet.lv text metadata (no external APIs).
See tv_programs/TV_CONTENT_IDENTIFICATION_PLAN.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Classification:
    content_type: str  # 'movie' | 'not_movie' | 'unknown'
    confidence: float
    reasoning: str


# Substring markers in titles/descriptions, case-insensitive (compounds, Latvian)
SERIES_MARKERS = (
    "seriāls",
    "telenovele",
    "cikls",
    "raidījums",
    "šovs",
    "ziņas",
    "panorāma",
    "intervija",
    "koncerts",
    "hronika",
    "sērija",
    "studija",
    "saeima",
    "sarunu",
    "brokastis",
    "jautājums",
    "rīta ",
)

MOVIE_TITLE_MARKERS = (
    "filma",
    "kinofilma",
)

# Curated list of local shows, news, and recurring slots to skip (one source of
# truth for the scraper exclusion filter).
EXCLUDED_LOCAL_SHOWS: frozenset[str] = frozenset(
    {
        "Aizliegtais paņēmiens",
        "Gudrs, vēl gudrāks",
        "V.I.P. - Veiksme. Intuīcija. Prāts",
        "Kas notiek Latvijā?",
        "Kas skatāms Filmzone?",
        "Panorāma",
        "Dienas ziņas",
        "Krustpunktā",
        "Rīta Panorāma",
        "Laika ziņas",
        "Sporta ziņas",
        "Nakts ziņas",
        "Kultūras ziņas",
        "Saki Jā!",
        "Spiegu spēles",
        "De Facto",
        "Basketbols.Basketbols: NBA.",
        "Leģendārais loms",
        "Aculiecinieks",
        "1 :1. Aktuālā intervija",
        "Sporta studija",
        "Autoziņas",
        "Bez Tabu",
        "900 sekundes",
        "Kultūršoks",
        "SuperBingo",
        "Kobra 17",
        "Tāskmāsters",
        "UgunsGrēks 4",
        "Vides fakti",
    }
)


def _normalize(s: str) -> str:
    if not s:
        return ""
    return s.casefold()


def is_movie_dedicated_channel(channel_key: str) -> bool:
    """True for Filmzone, Kinopolska, TV1000, Kino (slug or display name)."""
    if not channel_key:
        return False
    c = _normalize(channel_key).replace(" ", "_").replace("-", "_")
    for name in ("filmzone", "kinopolska", "tv1000", "kino"):
        if name in c:
            return True
    return False


def _has_substring(hay: str, needles: tuple[str, ...]) -> str | None:
    nlow = _normalize(hay)
    for needle in needles:
        if _normalize(needle) in nlow:
            return needle
    return None


def _duration(
    minutes: int | None,
) -> int | None:
    if minutes is None:
        return None
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        return None
    if m < 0:
        return 0
    return m


def classify(
    title_lv: str,
    description_lv: str,
    channel_key: str,
    duration_minutes: int | None,
) -> Classification:
    """
    Apply rules 1–5 from the TV content identification plan (order matters).
    """
    title = title_lv or ""
    desc = description_lv or ""
    combined = f"{title} {desc}"
    dur = _duration(duration_minutes)
    movie_ch = is_movie_dedicated_channel(channel_key)

    hit = _has_substring(title, MOVIE_TITLE_MARKERS)
    if hit:
        return Classification(
            content_type="movie",
            confidence=1.0,
            reasoning=f"title contains '{hit}' (movie keyword)",
        )

    hit = _has_substring(combined, SERIES_MARKERS)
    if hit:
        return Classification(
            content_type="not_movie",
            confidence=0.95,
            reasoning=f"title or description contains '{hit}' (non-movie keyword)",
        )

    if movie_ch and dur is not None and dur >= 60:
        return Classification(
            content_type="movie",
            confidence=0.9,
            reasoning="movie-dedicated channel and duration ≥ 60 min",
        )

    if movie_ch and dur is None:
        return Classification(
            content_type="unknown",
            confidence=0.0,
            reasoning="movie-dedicated channel but no duration; inconclusive",
        )

    if dur is not None:
        if not movie_ch and dur >= 80:
            return Classification(
                content_type="movie",
                confidence=0.8,
                reasoning="non-movie channel and duration ≥ 80 min",
            )
        if dur < 45:
            return Classification(
                content_type="not_movie",
                confidence=0.85,
                reasoning="duration < 45 min (likely short / magazine slot)",
            )

    return Classification(
        content_type="unknown",
        confidence=0.0,
        reasoning="no decisive keyword or duration rule; may be local listing",
    )

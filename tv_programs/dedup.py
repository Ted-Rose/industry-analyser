"""Show deduplication helpers (tv_show_normalization_plan.md §4.1).

A ``Show``'s identity is ``sha256(normalized title | normalized
description | season | episode)``. Normalization strips the rerun
marker ``(atkārtojums)``, HTML entities and whitespace differences so
re-airs of the same content resolve to one row.
"""

import hashlib
import re

_RERUN_RE = re.compile(r'\s*\(\s*atkārtojums\s*\)\s*', re.IGNORECASE)
_WS_RE = re.compile(r'\s+')
_ENTITY_RE = re.compile(r'&\w+;')
_TRAILING_DOTS_RE = re.compile(r'^[\s.]+|[\s.]+$')

# Live tet.lv series patterns (fetched 2026-10-01/02):
#   "Mīlas viesulis 21. Vācijas seriāls. 4471. sērija"
#   "Solījums 4. Spānijas telenovele. 613. sērija"
#   "Alpu dakteris 13. Seriāls. 14. (nosl.) sērija"
#   "Sisi 4. Vēsturisks seriāls. 6. (nosl.) sērija"
#   "Māja pie ezera. Daudzsēriju filma. 10. sērija"
#   "Garainis. 3. sezona (atkārtojums)"
_EPISODE_RE = re.compile(
    r'(\d+)\.\s*(?:\(\s*nosl\.?\s*\)\s*)?sērija', re.IGNORECASE
)
_SEASON_WORD_RE = re.compile(r'(\d+)\.\s*sezona', re.IGNORECASE)

# Words that mark the genre-descriptor segment of a series title.
# Deliberately excludes 'sērija'/'sezona' so episode numbers are never
# mistaken for the inline season number.
_GENRE_WORDS = (
    'seriāls', 'telenovele', 'daudsēriju', 'miniseriāls', 'filma',
    'šovs', 'raidījums', 'cikls', 'animācijas', 'dokumentāl',
)

_GENRE_TAIL_RE = re.compile(
    r'^(?P<base>.+?)\.\s*[^.]*(?:'
    + '|'.join(_GENRE_WORDS)
    + r')[^.]*$',
    re.IGNORECASE,
)

# "<Base> <season>. <genre fragment>" e.g. "Solījums 4. Spānijas
# telenovele" — the bare number before the genre word is the season.
_SEASON_INLINE_RE = re.compile(
    r'^(?P<base>.+?)\s+(?P<season>\d+)\.\s+'
    + r'(?P<genre>[^.]*(?:' + '|'.join(_GENRE_WORDS) + r')[^.]*)',
    re.IGNORECASE,
)


def normalize_title(title: str) -> str:
    """Strip the rerun marker, collapse whitespace, drop edge dots.
    Original case is preserved (casefold happens in the dedup key)."""
    if not title:
        return ''
    t = _RERUN_RE.sub('', title)
    t = _WS_RE.sub(' ', t)
    return _TRAILING_DOTS_RE.sub('', t)


def normalize_description(desc: str) -> str:
    """Same cleanup as the scraper's description handling."""
    if not desc:
        return ''
    d = _ENTITY_RE.sub('', desc)
    return _WS_RE.sub(' ', d).strip()


def _strip_genre_tail(text: str) -> str:
    """Drop a trailing ". <genre descriptor>" segment, if any."""
    m = _GENRE_TAIL_RE.match(text)
    if m:
        return _TRAILING_DOTS_RE.sub('', m.group('base'))
    return text


def parse_series_info(title: str) -> dict:
    """Extract series_title / season / episode from a normalized
    tet.lv title. Returns empty series_title and None numbers for
    non-series content."""
    episode = None
    ep_match = _EPISODE_RE.search(title)
    if ep_match:
        episode = int(ep_match.group(1))

    season = None
    series_title = ''
    se_match = _SEASON_WORD_RE.search(title)
    if se_match:
        season = int(se_match.group(1))
        base = _TRAILING_DOTS_RE.sub('', title[:se_match.start()])
        series_title = _strip_genre_tail(base)
    else:
        inline = _SEASON_INLINE_RE.match(title)
        if inline:
            season = int(inline.group('season'))
            series_title = _TRAILING_DOTS_RE.sub('', inline.group('base'))
        elif ep_match:
            base = _TRAILING_DOTS_RE.sub('', title[:ep_match.start()])
            series_title = _strip_genre_tail(base)

    return {
        'series_title': series_title,
        'season': season,
        'episode': episode,
    }


def compute_dedup_key(title, desc='', season=None, episode=None) -> str:
    parts = [
        (title or '').casefold(),
        (desc or '').casefold(),
        '' if season is None else str(int(season)),
        '' if episode is None else str(int(episode)),
    ]
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()


def annotate_result(result: dict) -> dict:
    """Add title_norm/desc_norm/series_*/dedup_key to a parsed
    program dict."""
    result['title_norm'] = normalize_title(result.get('title_lv'))
    result['desc_norm'] = normalize_description(
        result.get('description_lv')
    )
    result.update(parse_series_info(result['title_norm']))
    result['dedup_key'] = compute_dedup_key(
        result['title_norm'],
        result['desc_norm'],
        result['season'],
        result['episode'],
    )
    return result


def get_or_create_show(parsed: dict):
    """Resolve a parsed program dict to its Show, creating it on
    first sight. Returns (Show, created)."""
    from .models import Show

    c = parsed.get('classification')
    defaults = {
        'title_lv': parsed['title_norm'],
        'series_title': parsed.get('series_title') or '',
        'series_season': parsed.get('season'),
        'series_episode': parsed.get('episode'),
        'description_lv': parsed.get('desc_norm') or None,
        'image_url': parsed.get('image_url') or None,
        'content_type': c.content_type if c else 'unknown',
        'classification_confidence': c.confidence if c else 0.0,
        'classification_reasoning': (
            (c.reasoning or '')[:255] if c else None
        ),
    }
    return Show.objects.get_or_create(
        dedup_key=parsed['dedup_key'], defaults=defaults
    )

"""Show enrichment: IMDb (OMDb) re-integration + Cinemeta fallback
(tv_show_normalization_plan.md §5).

Enrichment runs once per *new* Show. Order per plan §2.7:

1. OMDb ``t=`` exact lookup with the Latvian title,
2. OMDb ``s=`` search, best candidate by SequenceMatcher, ``i=`` fetch,
3. LV→EN translation via the ``tv_programs.title_translation``
   AIJobSpec, then another OMDb pass with the English title,
4. Cinemeta search + meta fetch (key-free fallback),
5. ``enrichment_status='not_found'``.

All HTTP goes through ``request_fn`` — the scraper's throttled,
retrying ``make_request``.
"""

import json
import logging
import os
import re
import time
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from urllib.parse import quote, urlencode

from django.conf import settings
from django.utils import timezone

from ai_providers import errors as ai_errors
from ai_providers.types import GenerationOptions, PromptSpec

logger = logging.getLogger('tv_programs')

OMDB_BASE_URL = 'https://www.omdbapi.com/'
CINEMETA_BASE_URL = 'https://v3-cinemeta.strem.io'
OMDB_DAILY_LIMIT = 1000
OMDB_MIN_INTERVAL = 0.1
# Search candidates below these SequenceMatcher floors are junk hits
# (e.g. 'Slow TV: Migla' -> 'SM:TV Live') — better 'not_found' than a
# wrong IMDb link.
OMDB_SEARCH_MIN_RATIO = 0.5
CINEMETA_MIN_RATIO = 0.7
_TITLE_PROMPT = None


class OMDbClient:
    """Thin OMDb client (ported from feature/omdb-integration,
    commit 7c211ad): ``t=`` exact → ``s=`` search → ``i=`` fetch,
    with a daily request counter and 100ms throttle."""

    def __init__(self, request_fn, api_key, daily_limit=OMDB_DAILY_LIMIT,
                 min_interval=OMDB_MIN_INTERVAL):
        self._request = request_fn
        self.api_key = api_key
        self.daily_limit = daily_limit
        self.min_interval = min_interval
        self.request_count = 0
        self._last_request_time = 0.0

    def _request_json(self, **params):
        if self.request_count >= self.daily_limit:
            logger.warning('OMDb daily request limit reached')
            return None
        elapsed = time.time() - self._last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        url = OMDB_BASE_URL + '?' + urlencode(
            {**params, 'apikey': self.api_key}
        )
        response = self._request(url)
        self.request_count += 1
        self._last_request_time = time.time()
        logger.debug(
            'OMDb requests: %s/%s', self.request_count, self.daily_limit
        )
        if response is None or response.status != 200:
            return None
        data = json.loads(response.data)
        if data.get('Response') == 'True':
            return data
        return None

    def get_by_id(self, imdb_id):
        return self._request_json(i=imdb_id)

    def search_title(self, title, year=None, kind=None):
        """Exact ``t=`` lookup, then ``s=`` search + best candidate."""
        params = {'t': title}
        if year:
            params['y'] = year
        if kind:
            params['type'] = kind
        data = self._request_json(**params)
        if data:
            return data

        search = {'s': title}
        if kind:
            search['type'] = kind
        results = self._request_json(**search)
        if not results or 'Search' not in results:
            return None
        best = max(
            results['Search'],
            key=lambda r: SequenceMatcher(
                None,
                (r.get('Title') or '').casefold(),
                title.casefold(),
            ).ratio(),
        )
        ratio = SequenceMatcher(
            None,
            (best.get('Title') or '').casefold(),
            title.casefold(),
        ).ratio()
        if ratio < OMDB_SEARCH_MIN_RATIO:
            logger.debug(
                "OMDb search best candidate '%s' too dissimilar to "
                "'%s' (%.2f)", best.get('Title'), title, ratio,
            )
            return None
        return self.get_by_id(best['imdbID'])


def _load_title_prompt():
    global _TITLE_PROMPT
    if _TITLE_PROMPT is None:
        path = os.path.join(
            settings.BASE_DIR, 'tv_programs', 'prompts',
            'title_translate.txt',
        )
        with open(path, 'r', encoding='utf-8') as f:
            _TITLE_PROMPT = f.read()
    return _TITLE_PROMPT


def translate_title(title_lv, ai_client):
    """LV→EN title via the JobClient; None on any failure/cap."""
    try:
        result = ai_client.generate(
            PromptSpec(
                template_key='tv_programs.title_translate',
                template_text=_load_title_prompt(),
                input_text=title_lv,
                layout='system_v1',
            ),
            role='translate',
            options=GenerationOptions(
                json_mode=ai_client.supports_json_mode('translate')
            ),
        )
    except ai_errors.AIError as e:
        logger.warning(
            "Title translation failed for '%s': %s", title_lv, e
        )
        return None
    text = (result.text or '').strip()
    if not text:
        return None
    # Models sometimes wrap JSON in a markdown fence.
    m = re.match(r'^```(?:json)?\s*(.*?)\s*```$', text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "Title translation for '%s' was not JSON: %r",
            title_lv, text[:200],
        )
        return None
    title_en = (payload.get('title_en') or '').strip()
    return title_en or None


def _cinemeta_search(request_fn, title, kind):
    """Search one Cinemeta catalog; return best-matching meta dict."""
    url = (
        f'{CINEMETA_BASE_URL}/catalog/{kind}/top/'
        f'search={quote(title)}.json'
    )
    response = request_fn(url)
    if response is None or response.status != 200:
        return None
    metas = (json.loads(response.data) or {}).get('metas') or []
    if not metas:
        return None
    best = max(
        metas,
        key=lambda m: SequenceMatcher(
            None,
            (m.get('name') or '').casefold(),
            title.casefold(),
        ).ratio(),
    )
    ratio = SequenceMatcher(
        None,
        (best.get('name') or '').casefold(),
        title.casefold(),
    ).ratio()
    if ratio < CINEMETA_MIN_RATIO:
        logger.debug(
            "Cinemeta best candidate '%s' too dissimilar to '%s' "
            "(%.2f)", best.get('name'), title, ratio,
        )
        return None
    return best


def _cinemeta_meta(request_fn, kind, imdb_id):
    url = f'{CINEMETA_BASE_URL}/meta/{kind}/{imdb_id}.json'
    response = request_fn(url)
    if response is None or response.status != 200:
        return None
    return (json.loads(response.data) or {}).get('meta')


def cinemeta_lookup(request_fn, title, content_type=None):
    """Search Cinemeta for `title`, then fetch its meta record.

    Tries the catalog matching `content_type` first, then the other.
    Returns (meta dict, kind) or None.
    """
    kinds = ['movie', 'series']
    if content_type == 'not_movie':
        kinds.reverse()
    for kind in kinds:
        hit = _cinemeta_search(request_fn, title, kind)
        if not hit or not hit.get('id', '').startswith('tt'):
            continue
        meta = _cinemeta_meta(request_fn, kind, hit['id'])
        if meta:
            meta.setdefault('imdb_id', hit['id'])
            return meta, kind
    return None


def _decimal_or_none(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _apply_omdb(show, data, queried_title):
    if data.get('Title'):
        show.title_eng = show.title_eng or data['Title']
    plot = data.get('Plot')
    if plot and plot != 'N/A':
        show.description_eng = plot
    rating = _decimal_or_none(data.get('imdbRating'))
    if rating is not None:
        show.imdb_rating = rating
    rated = data.get('Rated')
    if rated and rated != 'N/A':
        show.pg_rating = rated
    year = data.get('Year')
    if year and year != 'N/A':
        show.year = year[:10]
    poster = data.get('Poster')
    if not show.image_url and poster and poster != 'N/A':
        show.image_url = poster
    show.imdb_id = data.get('imdbID')
    show.imdb_url = f'https://www.imdb.com/title/{show.imdb_id}/'
    show.title_match_ratio = SequenceMatcher(
        None,
        (data.get('Title') or '').casefold(),
        (queried_title or '').casefold(),
    ).ratio()
    show.enrichment_source = 'omdb'
    show.enrichment_status = 'enriched'
    show.enriched_at = timezone.now()


def _apply_cinemeta(show, meta, queried_title):
    if meta.get('name'):
        show.title_eng = show.title_eng or meta['name']
    rating = _decimal_or_none(meta.get('imdbRating'))
    if rating is not None:
        show.imdb_rating = rating
    release = meta.get('releaseInfo')
    if release:
        show.year = str(release)[:10]
    if not show.image_url and meta.get('poster'):
        show.image_url = meta['poster']
    show.imdb_id = meta.get('imdb_id') or meta.get('id')
    show.imdb_url = f'https://www.imdb.com/title/{show.imdb_id}/'
    show.title_match_ratio = SequenceMatcher(
        None,
        (meta.get('name') or '').casefold(),
        (queried_title or '').casefold(),
    ).ratio()
    show.enrichment_source = 'cinemeta'
    show.enrichment_status = 'enriched'
    show.enriched_at = timezone.now()


def enrich_show(show, omdb=None, ai_client=None, request_fn=None):
    """Run the enrichment chain on a Show and save it.

    ``omdb`` is an OMDbClient (None when OMDB_KEY is unset), ``ai_client``
    a JobClient for title translation, ``request_fn`` the throttled
    HTTP callable needed for the key-free Cinemeta fallback.
    """
    if show.is_excluded:
        return show
    try:
        _enrich(show, omdb, ai_client, request_fn)
    except Exception as e:
        logger.error(
            "Enrichment failed for show '%s': %s", show.title_lv, e
        )
        show.enrichment_status = 'failed'
    show.save()
    return show


def _enrich(show, omdb, ai_client, request_fn):
    data = None
    queried = show.title_lv
    if omdb is not None:
        data = omdb.search_title(show.title_lv)

    if (
        data is None
        and ai_client is not None
        and not show.title_eng
    ):
        title_en = translate_title(show.title_lv, ai_client)
        if title_en:
            show.title_eng = title_en
            if omdb is not None:
                data = omdb.search_title(title_en)
                queried = title_en

    if data is not None:
        _apply_omdb(show, data, queried)
        return

    if request_fn is not None:
        queried = show.title_eng or show.title_lv
        meta = cinemeta_lookup(
            request_fn, queried, show.content_type,
        )
        if meta is not None:
            _apply_cinemeta(show, meta[0], queried)
            return

    show.enrichment_status = 'not_found'

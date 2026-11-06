"""django-ninja router for the news SPA (mounted at /api/news/).

Read ops are public (auth=None) — the digest pages they replace
were public, including the gTTS clip endpoint whose pre-warm
fan-out must work for anonymous readers. The preferences ops keep
the default django_auth (session + CSRF) — they replaced the
@login_required form view. View logic is ported verbatim from the
retired views in news/views.py: `date`/`period` stay free-form
strings parsed by strptime inside the ops so malformed params
degrade to the default window instead of 422ing (the old page's
"never an error page" contract), and the `news.audio` import
stays lazy INSIDE the audio op — module-level it would take the
whole urlconf down when the optional gTTS/langdetect/GCS deps are
missing.
"""
import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import List, Optional

from django.db.models import Max, Min, Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from ninja import Field, Query, Router, Schema

from industry_analyser.api import ApiHttpError

from .models import (
    CONFIRMED_MATCH_STATUSES,
    NewsArticle,
    NewsArticleAudio,
    NewsDigest,
    NewsDigestItem,
    NewsSource,
    NewsSourcePreference,
    NewsStory,
)
from .preferences import ordered_story_articles

logger = logging.getLogger('news')

router = Router()

_LANG_RE = re.compile(r'^[a-z]{2}(-[a-zA-Z]{2})?$')


# --- Schemas ---


class DigestListItemOut(Schema):
    story_id: int              # toggle + story-card fetch key
    rank: int
    headline: str
    representative_lead: str   # audio desc clip

    @staticmethod
    def resolve_representative_lead(obj):
        return obj.story.representative_lead


class DigestOut(Schema):
    date: date
    items: List[DigestListItemOut]

    @staticmethod
    def resolve_items(obj):
        # Prefetched by the op — .all() hits the cache.
        return obj.items.all()


class DigestListOut(Schema):
    """The whole digest_list page payload — digests plus the
    effective filter state (the old template's context)."""
    digests: List[DigestOut]
    period: str                # 'day' | 'week' | 'all'
    anchor_date: Optional[date]
    range_start: Optional[date]
    range_end: Optional[date]
    min_date: Optional[date]   # date-input bounds
    max_date: Optional[date]


class ArticleRef(Schema):
    title: str
    link: str
    source_name: str


class DigestDetailItemOut(Schema):
    rank: int
    headline: str
    rationale: str
    topic_name: Optional[str]   # item.story.topic.name
    articles: List[ArticleRef]  # confirmed members only

    @staticmethod
    def resolve_topic_name(obj):
        topic = obj.story.topic
        return topic.name if topic else None

    @staticmethod
    def resolve_articles(obj):
        return [
            ArticleRef(
                title=a.title,
                link=a.link,
                source_name=a.source.name,
            )
            for a in getattr(obj.story, 'confirmed_articles', [])
        ]


class DigestDetailOut(Schema):
    date: date
    items: List[DigestDetailItemOut]


class StorySourceRef(Schema):
    source_slug: str
    source_name: str


class StoryArticleOut(Schema):
    id: int
    title: str
    lead: str
    link: str
    image_url: str
    published_at: Optional[datetime]  # ISO; SPA formats
    source_slug: str
    source_name: str

    @staticmethod
    def resolve_source_slug(obj):
        return obj.source.slug

    @staticmethod
    def resolve_source_name(obj):
        return obj.source.name


class StoryCardOut(Schema):
    """The _story_card.html context as JSON."""
    story_id: int
    article: StoryArticleOut
    # /news/article/<pk>/audio/ via reverse('news:article-audio')
    # when the ready-audio guard passes (status='ready',
    # non-empty file_path, isfile) else None — the card renders
    # <audio src> or the disabled "Klausīties" button off this
    # one field.
    audio_url: Optional[str]
    other_articles: List[StorySourceRef]


class AudioOut(Schema):
    audio_url: str


class PreferenceRowOut(Schema):
    slug: str
    name: str
    checked: bool
    rank: Optional[int]      # '' in the old form → null


class PreferencesOut(Schema):
    rows: List[PreferenceRowOut]


class PreferenceRowIn(Schema):
    slug: str = Field(max_length=100)
    rank: Optional[int] = None
    # No 1..99 bound — the form's min/max were UI hints; the
    # view accepted any int. Non-int JSON values 422, mildly
    # stricter than the view's ValueError→sink path (fine).


class PreferencesIn(Schema):
    """Presence in `rows` = the include-<slug> checkbox."""
    rows: List[PreferenceRowIn]


class PreferencesSavedOut(Schema):
    success: bool
    saved: int
    message: str


# --- Ops ---


@router.get('/digests/', auth=None, response=DigestListOut)
def list_digests(
    request,
    # No max_length — over-length garbage must hit the
    # strptime/membership fallbacks below (200 default window),
    # not pydantic's 422.
    date: Optional[str] = Query(None),
    period: Optional[str] = Query(None),
):
    """Digest index — verbatim port of the retired digest_list
    view: ?date=YYYY-MM-DD anchors a window, ?period=day|week|all
    picks its size, malformed values fall back to the 7-day
    window ending on the newest digest (never a 4xx/5xx)."""
    bounds = NewsDigest.objects.aggregate(
        first=Min('date'), last=Max('date'),
    )
    anchor = None
    if date:
        try:
            anchor = datetime.strptime(
                date, '%Y-%m-%d'
            ).date()
        except ValueError:
            anchor = None
    if period not in ('day', 'week', 'all'):
        # Unknown/absent period degrades to the weekly window —
        # a valid `date` merely re-anchors it.
        period = 'week'
    if anchor is None:
        anchor = bounds['last']

    digests = NewsDigest.objects.order_by('-date')
    range_start = range_end = None
    if period == 'day' and anchor is not None:
        digests = digests.filter(date=anchor)
        range_start = range_end = anchor
    elif period == 'week' and anchor is not None:
        range_start = anchor - timedelta(days=6)
        range_end = anchor
        digests = digests.filter(
            date__range=(range_start, range_end)
        )
    digests = digests.prefetch_related(Prefetch(
        'items',
        # select_related('story') makes each item's
        # representative_lead (the audio description clip)
        # cost zero extra queries.
        queryset=(
            NewsDigestItem.objects
            .select_related('story')
            .order_by('rank')
        ),
    ))
    return DigestListOut(
        digests=list(digests),
        period=period,
        anchor_date=anchor,
        range_start=range_start,
        range_end=range_end,
        min_date=bounds['first'],
        max_date=bounds['last'],
    )


@router.get('/digests/{date}/', auth=None, response=DigestDetailOut)
def digest_detail(request, date: str):
    """One digest day — verbatim port of the retired
    digest_detail view (strptime guard → 'Invalid date format'
    404, confirmed members only via the to_attr prefetch)."""
    try:
        day = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        raise Http404('Invalid date format') from None
    digest = get_object_or_404(NewsDigest, date=day)
    items = (
        digest.items
        .select_related('story__topic')
        # Only confirmed members render — 'candidate' links
        # await admin review and are not published coverage.
        .prefetch_related(Prefetch(
            'story__articles',
            queryset=(
                NewsArticle.objects
                .filter(
                    story_match_status__in=(
                        CONFIRMED_MATCH_STATUSES
                    )
                )
                .select_related('source')
            ),
            to_attr='confirmed_articles',
        ))
        .order_by('rank')
    )
    return DigestDetailOut(date=digest.date, items=list(items))


@router.get('/stories/{story_id}/', auth=None,
            response=StoryCardOut)
def story_card(
    request,
    story_id: int,
    source: Optional[str] = Query(None, max_length=100),
):
    """Story card for the inline reader — verbatim port of the
    retired story_fragment view: the confirmed member article
    from the reader's favorite covering outlet, or a
    `?source=<slug>` override when that outlet covered it.
    request.user rides the session even with auth=None, so
    logged-in readers keep preference-ordered picks."""
    story = get_object_or_404(NewsStory, pk=story_id)
    articles = ordered_story_articles(story, request.user)
    if not articles:
        raise Http404('Story has no confirmed member articles')
    article = articles[0]
    if source:
        # A stale switcher slug still renders — fall back to
        # the default pick when the outlet did not cover it.
        article = next(
            (a for a in articles if a.source.slug == source),
            article,
        )
    # Mirror article_audio's guards so the card never renders
    # an <audio> tag whose src would 404: skip empty file_path
    # rows and require the file on disk.
    audio = (
        NewsArticleAudio.objects
        .filter(article=article, status='ready')
        .exclude(file_path='')
        .order_by('-created_at', '-pk')
        .first()
    )
    ready_audio = (
        audio is not None
        and os.path.isfile(audio.file_path)
    )
    return StoryCardOut(
        story_id=story.pk,
        article=article,
        audio_url=(
            reverse('news:article-audio', args=[article.pk])
            if ready_audio
            else None
        ),
        other_articles=[
            StorySourceRef(
                source_slug=a.source.slug,
                source_name=a.source.name,
            )
            for a in articles
            if a.pk != article.pk
        ],
    )


@router.get('/audio/', auth=None, response=AudioOut)
def audio(
    request,
    text: str = Query(min_length=1, max_length=6000),
    lang: Optional[str] = Query(None, max_length=10),
    filename: Optional[str] = Query(None, max_length=200),
):
    """Public gTTS->GCS clip generator behind the digest page's
    audio buttons — port of the retired audio view. Stays
    unauthenticated: /news/ itself is public and the pre-warm
    fan-out must work for anonymous readers; abuse is bounded
    by content-addressed dedup, the text length cap and ~1s
    gTTS latency per genuinely new text. Schema bounds 422 the
    malformed cases the view 400ed (uniform with the rest of
    the API); the `lang` shape check stays manual so 'english'
    still 400s rather than 422ing."""
    # Lazy import: news.audio pulls optional media deps (gTTS,
    # langdetect, google-cloud-storage). Kept off the module
    # path so a missing dep hits this endpoint only — module-
    # level, it would break the router import in
    # industry_analyser/urls.py and take the whole urlconf
    # down with it. A deployment whose bundle lacks the deps
    # (the Vercel lambda) degrades to the same 502 the SPA
    # already treats as "audio unavailable" — not an
    # unhandled 500.
    try:
        from .audio import AudioGenerationError, text_to_audio
    except ImportError as exc:
        logger.warning('audio media deps unavailable: %s', exc)
        raise ApiHttpError(
            502, 'audio generation unavailable'
        ) from exc
    lang = lang or None
    filename = filename or None
    if lang is not None and not _LANG_RE.match(lang):
        raise ApiHttpError(400, 'invalid lang')
    try:
        url = text_to_audio(text, lang=lang, filename=filename)
    except ValueError as exc:
        raise ApiHttpError(400, str(exc)) from exc
    except AudioGenerationError as exc:
        logger.warning('audio generation failed: %s', exc)
        raise ApiHttpError(502, str(exc)) from exc
    return AudioOut(audio_url=url)


@router.get('/preferences/', response=PreferencesOut)
def get_preferences(request):
    """Enabled sources (-importance_weight, pk) joined to the
    user's NewsSourcePreference rank map — the rows the retired
    preferences form rendered."""
    sources = list(
        NewsSource.objects.filter(is_enabled=True)
        .order_by('-importance_weight', 'pk')
    )
    ranks = dict(
        NewsSourcePreference.objects.filter(user=request.user)
        .values_list('source_id', 'rank')
    )
    return PreferencesOut(rows=[
        PreferenceRowOut(
            slug=source.slug,
            name=source.name,
            checked=source.pk in ranks,
            rank=ranks.get(source.pk),
        )
        for source in sources
    ])


@router.post('/preferences/', response=PreferencesSavedOut)
def save_preferences(request, payload: PreferencesIn):
    """Replace the user's outlet ranking — verbatim port of the
    retired preferences view's POST: presence in `rows` is the
    include checkbox, checked-but-unranked sinks below every
    numbered pick (canonical source order breaks the tie),
    saved rows renumber 1..N, disabled/unknown slugs ignored."""
    sources = list(
        NewsSource.objects.filter(is_enabled=True)
        .order_by('-importance_weight', 'pk')
    )
    submitted = {row.slug: row.rank for row in payload.rows}
    ranked = []
    for index, source in enumerate(sources):
        if source.slug not in submitted:
            continue
        rank = submitted[source.slug]
        if rank is None:
            # Checked but unranked sinks below every numbered
            # pick; input order breaks the tie.
            rank = len(sources) + 1
        ranked.append((rank, index, source))
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    NewsSourcePreference.objects.filter(
        user=request.user
    ).delete()
    NewsSourcePreference.objects.bulk_create([
        NewsSourcePreference(
            user=request.user, source=source, rank=position,
        )
        for position, (_, _, source)
        in enumerate(ranked, start=1)
    ])
    return PreferencesSavedOut(
        success=True,
        saved=len(ranked),
        message='Preferences saved.',
    )

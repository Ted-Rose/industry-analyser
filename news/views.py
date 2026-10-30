"""Digest pages — plain Django templates (MVP UI; the React SPA
and ninja API are out of scope for this feature)."""
import logging
import os
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

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


def digest_list(request):
    digests = (
        NewsDigest.objects.order_by('-date')
        .prefetch_related(Prefetch(
            'items',
            queryset=NewsDigestItem.objects.order_by('rank'),
        ))
    )
    return render(
        request, 'news/digest_list.html', {'digests': digests}
    )


def digest_detail(request, date):
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
    return render(
        request,
        'news/digest_detail.html',
        {'digest': digest, 'items': items},
    )


def story_fragment(request, pk):
    """Partial story card for the inline reader — the confirmed
    member article from the reader's favorite covering outlet,
    or a `?source=<slug>` override when that outlet covered it."""
    story = get_object_or_404(NewsStory, pk=pk)
    articles = ordered_story_articles(story, request.user)
    if not articles:
        raise Http404('Story has no confirmed member articles')
    article = articles[0]
    slug = request.GET.get('source')
    if slug:
        # A stale switcher link still renders — fall back to
        # the default pick when the slug did not cover it.
        article = next(
            (a for a in articles if a.source.slug == slug),
            article,
        )
    return render(
        request,
        'news/_story_card.html',
        {
            'story': story,
            'article': article,
            'other_articles': [
                a for a in articles if a.pk != article.pk
            ],
            'ready_audio': NewsArticleAudio.objects.filter(
                article=article, status='ready',
            ).exists(),
        },
    )


def article_audio(request, pk):
    """Audio seam for a future TTS feature: serve a ready
    NewsArticleAudio's file_path when it exists on disk. No
    generator fills the table yet, so this 404s today — the
    URL contract is what matters."""
    audio = (
        NewsArticleAudio.objects
        .filter(article_id=pk, status='ready')
        .exclude(file_path='')
        .first()
    )
    if audio is None or not os.path.isfile(audio.file_path):
        raise Http404('No ready audio for this article')
    return FileResponse(open(audio.file_path, 'rb'))


@login_required
def preferences(request):
    """Rank favorite outlets — checked sources ordered by their
    submitted rank become NewsSourcePreference rank 1..N;
    anonymous readers are redirected to the admin login."""
    sources = list(
        NewsSource.objects.filter(is_enabled=True)
        .order_by('-importance_weight', 'pk')
    )
    if request.method == 'POST':
        ranked = []
        for index, source in enumerate(sources):
            if not request.POST.get(f'include-{source.slug}'):
                continue
            try:
                rank = int(
                    request.POST.get(f'rank-{source.slug}', '')
                )
            except ValueError:
                # Checked but unranked sinks below every
                # numbered pick; input order breaks the tie.
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
        return redirect('news:preferences')
    ranks = dict(
        NewsSourcePreference.objects.filter(user=request.user)
        .values_list('source_id', 'rank')
    )
    rows = [
        {
            'source': source,
            'checked': source.pk in ranks,
            'rank': ranks.get(source.pk, ''),
        }
        for source in sources
    ]
    return render(
        request, 'news/preferences.html', {'rows': rows}
    )

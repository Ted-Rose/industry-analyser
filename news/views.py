"""Digest pages — plain Django templates (MVP UI; the React SPA
and ninja API are out of scope for this feature)."""
from datetime import datetime

from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import (
    CONFIRMED_MATCH_STATUSES,
    NewsArticle,
    NewsDigest,
    NewsDigestItem,
)


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

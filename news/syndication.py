"""Outgoing RSS feed — the flip side of feeds.py (the inbound
source inventory): the last 7 days of NewsDigest items
syndicated for feed readers and crawlers that cannot execute
the /news/ SPA.

One RSS item per digest item (ranked story). The item link is
the digest-day page; the description carries the representative
lead plus every confirmed member article's URL, so a robot sees
the week's digest and the outlet links in one fetch.
"""
import logging
from datetime import datetime, timedelta, time

from django.contrib.syndication.views import Feed
from django.db.models import Prefetch
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from .models import (
    CONFIRMED_MATCH_STATUSES,
    NewsArticle,
    NewsDigest,
    NewsDigestItem,
)

logger = logging.getLogger('news')

# Freshness window shared with news.views.llms_txt — the digest
# surface robots are pointed at (sitemap keeps the full history).
DIGEST_WINDOW_DAYS = 7


def recent_digest_items():
    """Digest items from the 7-day window ending on the newest
    digest, oldest-window boundaries included. Confirmed member
    articles are prefetched onto each story as
    ``confirmed_articles`` (same contract as api.digest_detail).
    Empty queryset when no digest exists yet."""
    latest = (
        NewsDigest.objects.order_by('-date')
        .values_list('date', flat=True)
        .first()
    )
    if latest is None:
        return NewsDigestItem.objects.none()
    window_start = latest - timedelta(days=DIGEST_WINDOW_DAYS - 1)
    return (
        NewsDigestItem.objects
        .filter(digest__date__range=(window_start, latest))
        .select_related('digest', 'story__topic')
        .prefetch_related(Prefetch(
            'story__articles',
            queryset=(
                NewsArticle.objects
                .filter(
                    story_match_status__in=CONFIRMED_MATCH_STATUSES
                )
                .select_related('source')
            ),
            to_attr='confirmed_articles',
        ))
        .order_by('-digest__date', 'rank')
    )


def digest_day_url(date):
    return reverse('news:digest-detail', args=[date.isoformat()])


class NewsDigestFeed(Feed):
    title = 'Industry Analyser — Latvian news digest'
    link = '/news/'
    description = (
        'Daily ranked digest of Latvian news stories across '
        'outlets.'
    )

    def items(self):
        return recent_digest_items()

    def item_title(self, item):
        return item.headline

    def item_link(self, item):
        # Relative — the syndication framework absolutizes it
        # against the request host via add_domain().
        return digest_day_url(item.digest.date)

    def item_pubdate(self, item):
        return timezone.make_aware(
            datetime.combine(item.digest.date, time.min)
        )

    def item_guid(self, item):
        return (
            f'digest:{item.digest.date.isoformat()}'
            f':story:{item.story_id}'
        )

    def item_description(self, item):
        lead = item.story.representative_lead
        links = ''.join(
            '<li><a href="{url}">{title}</a> ({source})</li>'.format(
                url=escape(a.link),
                title=escape(a.title),
                source=escape(a.source.name),
            )
            for a in getattr(item.story, 'confirmed_articles', [])
        )
        description = (
            f'<p>{escape(lead)}</p>' if lead else ''
        ) + (f'<ul>{links}</ul>' if links else '')
        return description or item.headline

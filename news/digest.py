"""Daily digest builder — rank the day's unique stories by
multi-outlet coverage x topic weight.

Hook point for a later PR: an LLM summarizer/cluster-refiner
(JobClient, ai_providers) can post-process the ranked items
here — the MVP deliberately ships zero paid AI calls.
"""
import logging

from django.db import transaction

from .models import (
    CONFIRMED_MATCH_STATUSES,
    NewsDigest,
    NewsDigestItem,
    NewsStory,
)

logger = logging.getLogger('news')


def _confirmed_members(story):
    """Confirmed member articles — 'candidate' links await admin
    review and must not count as coverage in the digest."""
    # .all() rides the caller's prefetch_related('articles__source').
    return [
        a for a in story.articles.all()
        if a.story_match_status in CONFIRMED_MATCH_STATUSES
    ]


def _pick_headline(story):
    """Title of the confirmed member article from the highest
    importance_weight source; ties broken by longest lead.
    Falls back to the story title when it has none."""
    members = _confirmed_members(story)
    if not members:
        return story.title
    best = max(
        members,
        key=lambda a: (a.source.importance_weight, len(a.lead)),
    )
    return best.title


def _rationale(story):
    # The outlet count is recomputed from live confirmed
    # membership — story.source_count is only refreshed by
    # clustering's _refresh_story and goes stale when an admin
    # edits an article's story/story_match_status.
    slugs = sorted(
        {a.source.slug for a in _confirmed_members(story)}
    )
    plural = 's' if len(slugs) != 1 else ''
    return f"{len(slugs)} outlet{plural}: {', '.join(slugs)}"


def build_digest(date, top_n=5, dry_run=False):
    """Build/rebuild the digest for ``date`` (datetime.date).

    Stories: published_date == date with an enabled topic, ranked
    by importance_score then recency, top_n taken. Rebuild is
    idempotent — old items are replaced wholesale.
    Returns {'date': date, 'items': [(rank, headline, rationale)]}.
    """
    stories = (
        NewsStory.objects.filter(
            published_date=date,
            topic__is_enabled=True,
            # At least one confirmed member — an all-'candidate'
            # story is admin-review material, not published
            # coverage.
            articles__story_match_status__in=(
                CONFIRMED_MATCH_STATUSES
            ),
        )
        .distinct()
        .prefetch_related('articles__source')
        .order_by('-importance_score', '-last_seen')[:top_n]
    )

    items = []
    for rank, story in enumerate(stories, start=1):
        headline = _pick_headline(story)
        rationale = _rationale(story)[:300]
        items.append((rank, headline, rationale, story))

    if not dry_run:
        # Atomic: a crash between delete and bulk_create must not
        # leave an empty digest for the day.
        with transaction.atomic():
            digest, _ = NewsDigest.objects.update_or_create(
                date=date
            )
            digest.items.all().delete()
            NewsDigestItem.objects.bulk_create([
                NewsDigestItem(
                    digest=digest,
                    story=story,
                    rank=rank,
                    headline=headline[:500],
                    rationale=rationale,
                )
                for rank, headline, rationale, story in items
            ])
        logger.info(
            'Digest %s: %d item(s) written', date, len(items)
        )
    else:
        logger.info(
            '[dry-run] digest %s: %d item(s)', date, len(items)
        )

    return {
        'date': date,
        'items': [
            (rank, headline, rationale)
            for rank, headline, rationale, _ in items
        ],
    }

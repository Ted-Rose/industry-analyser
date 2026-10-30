"""Per-user news source ranking — decides which outlet's
article a story shows in the inline reader
(docs/plans/news_story_reader_plan.md)."""
from .models import (
    CONFIRMED_MATCH_STATUSES,
    NewsSource,
    NewsSourcePreference,
)


def ordered_sources(user):
    """Enabled NewsSource list: the user's preferred sources
    first by rank asc, then the rest by importance_weight desc
    with pk as final tie-break — deterministic. Anonymous or a
    user with no prefs collapses to the weight ordering."""
    sources = list(
        NewsSource.objects.filter(is_enabled=True)
        .order_by('-importance_weight', 'pk')
    )
    if not getattr(user, 'is_authenticated', False):
        return sources
    ranks = dict(
        NewsSourcePreference.objects.filter(user=user)
        .values_list('source_id', 'rank')
    )
    if not ranks:
        return sources
    # sort() is stable, so non-preferred sources keep the
    # (-weight, pk) order established above.
    sources.sort(
        key=lambda s: (0, ranks[s.pk]) if s.pk in ranks else (1, 0)
    )
    return sources


def ordered_story_articles(story, user):
    """The story's confirmed member articles sorted by their
    source's position in ordered_sources(user). Index 0 is
    'the favorite that covered it' — or the best non-favorite
    when no favorite did."""
    articles = list(
        story.articles
        .filter(story_match_status__in=CONFIRMED_MATCH_STATUSES)
        .select_related('source')
    )
    positions = {
        source.pk: index
        for index, source in enumerate(ordered_sources(user))
    }
    # Members from disabled sources sort last but stay
    # eligible — the story covered it, the feed is just off.
    articles.sort(
        key=lambda a: (
            positions.get(a.source_id, len(positions)),
            a.source_id,
            a.pk,
        )
    )
    return articles

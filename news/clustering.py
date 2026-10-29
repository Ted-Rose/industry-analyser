"""Jaccard story clustering — group same-day articles from
different outlets covering the same story.

Blocking precedent: classified_ads/property_matcher.py —
candidate stories are narrowed to published_date +- 1 day, then
scored by token-set Jaccard against member article titles
(fallback: the story title). Outcomes: 'auto' link, 'candidate'
link (admin-reviewable) or a fresh NewsStory.

Latvian is heavily inflected ("budžetu"/"budžets",
"Saeima"/"Saeimā"), so tokens are compared as 4-char prefix
stems — crude, but it collapses the common declensions without
a stemmer dependency.
"""
import logging
import re
import unicodedata
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import NewsArticle, NewsStory

logger = logging.getLogger('news')

AUTO_THRESHOLD = 0.45
CANDIDATE_THRESHOLD = 0.30
# Token prefix length — collapses Latvian declension endings.
STEM_LEN = 4

# ~40-word Latvian stopword list.
STOPWORDS = frozenset({
    'un', 'ir', 'ka', 'par', 'uz', 'ar', 'no', 'kas', 'arī',
    'pēc', 'bija', 'to', 'tas', 'vai', 'bet', 'jā', 'pie',
    'līdz', 'kad', 'jau', 'tikai', 'savu', 'šī', 'tiek', 'var',
    'būt', 'kļūst', 'saka', 'vēl', 'gan', 'tā', 'viņš', 'viņa',
    'mums', 'es', 'tu', 'jūs', 'viņu',
})

_WORD_RE = re.compile(r'\w+')


def _tokens(text):
    """Stopword-filtered 4-char-stem token set for a title."""
    norm = unicodedata.normalize('NFKC', text or '').lower()
    return {
        w[:STEM_LEN]
        for w in _WORD_RE.findall(norm)
        if w not in STOPWORDS
    }


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _article_date(article):
    if article.published_at is not None:
        return article.published_at.date()
    return article.first_seen.date()


def _best_story(article_tokens, stories):
    """(story, score) of the best candidate, or (None, best_score)
    when nothing reaches CANDIDATE_THRESHOLD."""
    best_story = None
    best_score = 0.0
    for story in stories:
        titles = [
            a.title for a in story.articles.all()
        ] or [story.title]
        score = max(
            _jaccard(article_tokens, _tokens(t)) for t in titles
        )
        if score > best_score:
            best_story = story
            best_score = score
    return best_story, best_score


def _refresh_story(story, dry_run=False):
    """Recompute source_count and importance_score from member
    articles; save() bumps last_seen via auto_now."""
    members = list(story.articles.select_related('source'))
    sources = {a.source_id for a in members}
    story.source_count = len(sources)
    weight = story.topic.weight if story.topic_id else 1.0
    if members:
        mean_importance = (
            sum(a.source.importance_weight for a in members)
            / len(members)
        )
    else:
        mean_importance = 0.0
    story.importance_score = (
        story.source_count * (weight or 1.0) * mean_importance
    )
    if not dry_run:
        story.save()


def link_unmatched_articles(days=2, dry_run=False):
    """Assign recent 'unmatched' articles to NewsStory clusters.

    Returns stats: {'linked', 'new_stories', 'skipped'}.
    """
    today = timezone.localdate()
    cutoff = today - timedelta(days=days)
    candidates = (
        NewsArticle.objects
        .filter(story_match_status='unmatched')
        .filter(
            Q(published_at__date__gte=cutoff)
            | Q(
                published_at__isnull=True,
                first_seen__date__gte=cutoff,
            )
        )
        .select_related('source', 'topic')
        .order_by('published_at', 'id')
    )

    stats = {'linked': 0, 'new_stories': 0, 'skipped': 0}
    for article in candidates:
        article_tokens = _tokens(article.title)
        if not article_tokens:
            stats['skipped'] += 1
            continue
        day = _article_date(article)
        stories = (
            NewsStory.objects.filter(
                published_date__range=(
                    day - timedelta(days=1),
                    day + timedelta(days=1),
                )
            )
            .prefetch_related('articles')
        )
        story, score = _best_story(article_tokens, stories)

        if story is not None and score >= AUTO_THRESHOLD:
            status = 'auto'
        elif story is not None and score >= CANDIDATE_THRESHOLD:
            status = 'candidate'
        else:
            # No story close enough — start a new cluster.
            story = NewsStory(
                title=article.title[:500],
                representative_lead=article.lead,
                topic=article.topic,
                published_date=day,
            )
            status = 'auto'
            score = None
            if not dry_run:
                story.save()
            stats['new_stories'] += 1
            logger.info('New story: %s', story.title)

        article.story = story
        article.story_match_status = status
        article.story_match_score = score
        if score is not None:
            stats['linked'] += 1
        if not dry_run:
            article.save(
                update_fields=[
                    'story', 'story_match_status',
                    'story_match_score',
                ]
            )
            _refresh_story(story)

    logger.info(
        'Story linking: %d linked, %d new stories, %d skipped',
        stats['linked'], stats['new_stories'], stats['skipped'],
    )
    return stats

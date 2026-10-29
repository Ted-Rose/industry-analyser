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

Pure-number stems (years, dates) are dropped from tokens and
auto-merge additionally requires a minimum number of shared
"substantive" stems — otherwise generic date/boilerplate stems
glue distinct stories together ("Valsts budžets 2027. gadam"
vs "Pašvaldību budžets 2027. gadam" would score 0.50 on stems
budž+gada alone).
"""
import logging
import re
import unicodedata
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import (
    CONFIRMED_MATCH_STATUSES,
    NewsArticle,
    NewsStory,
)

logger = logging.getLogger('news')

AUTO_THRESHOLD = 0.45
CANDIDATE_THRESHOLD = 0.30
# Token prefix length — collapses Latvian declension endings.
STEM_LEN = 4
# Auto-merge needs at least this many shared stems that are not
# date boilerplate — the Jaccard score alone cannot tell a real
# overlap from same-year boilerplate.
MIN_SHARED_SUBSTANTIVE = 2

# Stems that name a date rather than a story — the year-word
# family (gada/gadam/gadu/gadā/gads). They stay in the Jaccard
# token sets but never count as substantive shared stems.
_DATE_STEMS = frozenset({'gada', 'gadu', 'gadā', 'gads'})

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
    """Stopword-filtered 4-char-stem token set for a title.

    Pure-number stems (years like 2027, dates) are dropped —
    every same-year headline shares them, so they inflate the
    Jaccard between unrelated stories.
    """
    norm = unicodedata.normalize('NFKC', text or '').lower()
    stems = set()
    for word in _WORD_RE.findall(norm):
        if word in STOPWORDS:
            continue
        stem = word[:STEM_LEN]
        if stem.isdigit():
            continue
        stems.add(stem)
    return stems


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _article_date(article):
    if article.published_at is not None:
        return article.published_at.date()
    return article.first_seen.date()


def _best_story(article_tokens, stories):
    """(story, score, shared_stems) of the best member title —
    shared_stems belongs to that single title.

    Titles rank by (meets the auto-merge bar, score, substantive
    stem count): a member title that clears the auto bar on its
    own beats a higher-scoring title whose overlap is date
    boilerplate — otherwise the argmax title alone would decide
    auto-vs-candidate for the whole story.
    (None, best_score, frozenset()) when nothing is close."""
    best_story = None
    best_key = (False, 0.0, 0)
    best_shared = frozenset()
    for story in stories:
        titles = [
            a.title for a in story.articles.all()
        ] or [story.title]
        for title in titles:
            story_tokens = _tokens(title)
            score = _jaccard(article_tokens, story_tokens)
            shared = article_tokens & story_tokens
            substantive = len(shared - _DATE_STEMS)
            key = (
                score >= AUTO_THRESHOLD
                and substantive >= MIN_SHARED_SUBSTANTIVE,
                score,
                substantive,
            )
            if key > best_key:
                best_story = story
                best_key = key
                best_shared = shared
    return best_story, best_key[1], best_shared


def _refresh_story(story, dry_run=False):
    """Recompute source_count and importance_score from member
    articles; save() bumps last_seen via auto_now.

    Only confirmed members ('auto'/'manual') count — 'candidate'
    links await admin review and must not inflate the digest.
    A story with zero confirmed members degrades to
    source_count/importance_score 0."""
    members = [
        a for a in story.articles.select_related('source')
        if a.story_match_status in CONFIRMED_MATCH_STATUSES
    ]
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

    Returns stats: {'linked', 'new_stories'}.
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

    stats = {'linked': 0, 'new_stories': 0}
    for article in candidates:
        article_tokens = _tokens(article.title)
        day = _article_date(article)
        if not article_tokens:
            # A title that stems to nothing (stopwords/numbers
            # only) can never match — fall through to the
            # new-story branch so it doesn't stay 'unmatched'
            # and get rescanned every run.
            story, score, shared = None, 0.0, frozenset()
        else:
            stories = (
                NewsStory.objects.filter(
                    published_date__range=(
                        day - timedelta(days=1),
                        day + timedelta(days=1),
                    )
                )
                .prefetch_related('articles')
            )
            story, score, shared = _best_story(
                article_tokens, stories
            )
        # Stems shared with the best-matching title that are not
        # date boilerplate — auto-merge requires several so a
        # shared year + one generic noun cannot glue distinct
        # stories.
        substantive = shared - _DATE_STEMS

        if (
            story is not None
            and score >= AUTO_THRESHOLD
            and len(substantive) >= MIN_SHARED_SUBSTANTIVE
        ):
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
        'Story linking: %d linked, %d new stories',
        stats['linked'], stats['new_stories'],
    )
    return stats

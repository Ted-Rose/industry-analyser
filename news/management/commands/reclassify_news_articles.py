"""Backfill topic classification for existing NewsArticle rows.

Articles are only classified at insert/update time by
scrape_news, so existing rows keep whatever the old
\b-bounded matcher assigned — mostly NULL (79% untopicked in
prod). This command re-runs the stem-aware classify_topic and,
for every NewsStory whose members changed, recomputes the
story topic (most common non-null confirmed-member topic) and
re-runs clustering's _refresh_story so source_count and
importance_score pick up the new topic weight.

Command precedent: tv_programs' reclassify_tv_programs.
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from news.classification import classify_topic
from news.clustering import _refresh_story
from news.models import (
    CONFIRMED_MATCH_STATUSES,
    NewsArticle,
    NewsStory,
    NewsTopic,
)


def _member_topic_id(story, overrides):
    """Most common non-null topic_id across confirmed ('auto' /
    'manual') member articles; None when they are all
    untopicked. ``overrides`` maps article pk -> pending
    topic_id so --dry-run can preview post-update values
    without writing."""
    counts = Counter()
    for article in story.articles.all():
        if (
            article.story_match_status
            not in CONFIRMED_MATCH_STATUSES
        ):
            continue
        topic_id = overrides.get(article.id, article.topic_id)
        if topic_id is not None:
            counts[topic_id] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


class Command(BaseCommand):
    help = (
        'Re-run stem-aware topic classification on existing '
        'NewsArticle rows (default: untopicked only) and refresh '
        'touched NewsStory topic/importance'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help='Only articles published (or first seen) within '
                 'the last N days (default: no limit)',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            dest='all_articles',
            help='Reclassify every article, not only untopicked '
                 'ones — stemming may change existing '
                 'assignments',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Report what would change without writing',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            dest='batch_size',
            help='Rows per bulk_update flush (default: 500)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        batch_size = options['batch_size']
        topics = list(NewsTopic.objects.filter(is_enabled=True))

        qs = NewsArticle.objects.all()
        if not options['all_articles']:
            qs = qs.filter(topic__isnull=True)
        if options['days'] is not None:
            cutoff = (
                timezone.localdate()
                - timedelta(days=options['days'])
            )
            qs = qs.filter(
                Q(published_at__date__gte=cutoff)
                | Q(
                    published_at__isnull=True,
                    first_seen__date__gte=cutoff,
                )
            )
        qs = qs.order_by('id').select_related('topic')

        scanned = 0
        to_slug = Counter()
        moves = Counter()
        touched_story_ids = set()
        # article pk -> new topic_id; feeds _member_topic_id and
        # doubles as the dry-run preview.
        overrides = {}
        batch = []
        for article in qs.iterator():
            scanned += 1
            topic = classify_topic(
                article.title, article.lead, topics,
            )
            new_id = topic.id if topic is not None else None
            if new_id == article.topic_id:
                continue
            old_slug = (
                article.topic.slug
                if article.topic_id and article.topic
                else '(none)'
            )
            new_slug = topic.slug if topic is not None else '(none)'
            to_slug[new_slug] += 1
            moves[f'{old_slug} -> {new_slug}'] += 1
            overrides[article.id] = new_id
            if article.story_id:
                touched_story_ids.add(article.story_id)
            if dry_run:
                continue
            article.topic_id = new_id
            batch.append(article)
            if len(batch) >= batch_size:
                NewsArticle.objects.bulk_update(batch, ['topic'])
                batch = []
        if batch:
            NewsArticle.objects.bulk_update(batch, ['topic'])

        stories_refreshed = 0
        for story_id in sorted(touched_story_ids):
            story = NewsStory.objects.get(pk=story_id)
            story.topic_id = _member_topic_id(story, overrides)
            # Sets source_count + importance_score (using the new
            # topic weight) and saves unless dry_run.
            _refresh_story(story, dry_run=dry_run)
            stories_refreshed += 1

        verb = 'would update' if dry_run else 'updated'
        self.stdout.write(
            f'scanned={scanned} {verb}={sum(to_slug.values())} '
            f'stories_refreshed={stories_refreshed}'
        )
        for slug, count in to_slug.most_common():
            self.stdout.write(f'  -> {slug}: {count}')
        if options['all_articles']:
            for move, count in moves.most_common():
                self.stdout.write(f'    {move}: {count}')
        style = self.style.WARNING if dry_run else self.style.SUCCESS
        self.stdout.write(style('reclassify complete'))

"""Verified RSS feed inventory (tested 2026-10-29, all return
RSS 2.0) plus the idempotent seeder for sources and topics.

category_strategy: 'tag' = <category> elements, 'url' = link path
segments, 'none' = no usable category signal in the feed.
"""

# (slug, name, feed_url, language, category_strategy,
#  importance_weight[, is_enabled])
# Weights: lsm/diena/db/lvportals 1.2, ir/rebaltica 1.3,
# delfi/tvnet/apollo 1.0, jauns 0.5 (tabloid).
NEWS_FEEDS = (
    {
        'slug': 'lsm',
        'name': 'LSM',
        'feed_url': 'https://www.lsm.lv/rss/',
        'language': 'lv',
        'category_strategy': 'url',
        'importance_weight': 1.2,
    },
    {
        'slug': 'delfi',
        'name': 'Delfi',
        'feed_url': 'https://www.delfi.lv/rss/index.xml',
        'language': 'lv',
        'category_strategy': 'tag',
        'importance_weight': 1.0,
    },
    {
        'slug': 'tvnet',
        'name': 'TVNET',
        'feed_url': 'https://www.tvnet.lv/rss',
        'language': 'lv',
        'category_strategy': 'tag',
        'importance_weight': 1.0,
    },
    {
        'slug': 'apollo',
        'name': 'Apollo',
        'feed_url': 'https://www.apollo.lv/rss',
        'language': 'lv',
        'category_strategy': 'tag',
        'importance_weight': 1.0,
    },
    {
        'slug': 'diena',
        'name': 'Diena',
        'feed_url': 'https://www.diena.lv/rss',
        'language': 'lv',
        'category_strategy': 'url',
        'importance_weight': 1.2,
    },
    {
        'slug': 'db',
        'name': 'Dienas Bizness',
        'feed_url': 'https://www.db.lv/rss',
        'language': 'lv',
        'category_strategy': 'none',
        'importance_weight': 1.2,
    },
    {
        'slug': 'lvportals',
        'name': 'LV portāls',
        'feed_url': 'https://lvportals.lv/rss',
        'language': 'lv',
        'category_strategy': 'none',
        'importance_weight': 1.2,
    },
    {
        'slug': 'ir',
        'name': 'IR',
        'feed_url': 'https://www.ir.lv/rss/',
        'language': 'lv',
        'category_strategy': 'none',
        'importance_weight': 1.3,
    },
    {
        'slug': 'rebaltica',
        'name': 'Re:Baltica',
        'feed_url': 'https://rebaltica.lv/feed/',
        'language': 'lv',
        'category_strategy': 'tag',
        'importance_weight': 1.3,
    },
    {
        'slug': 'jauns',
        'name': 'Jauns.lv',
        'feed_url': 'https://jauns.lv/rss',
        'language': 'lv',
        'category_strategy': 'tag',
        'importance_weight': 0.5,
    },
    {
        'slug': 'lsm-en',
        'name': 'LSM English',
        'feed_url': 'https://eng.lsm.lv/rss/',
        'language': 'en',
        # English content would not cluster with Latvian.
        'is_enabled': False,
        'category_strategy': 'url',
        'importance_weight': 1.0,
    },
)


def ensure_seeded(dry_run=False, sync=False):
    """Idempotently seed NewsSource rows from NEWS_FEEDS and
    NewsTopic rows from TOPICS.

    Default is get_or_create only — admin edits are never
    overwritten. With ``sync=True`` the seed's ``keywords`` and
    ``weight`` are written onto existing topic rows whose slug
    matches a seed slug (the maintainer's explicit "adopt new
    seed keyword lists" switch; ``name`` and ``is_enabled`` are
    still left alone). Returns counts of rows created/updated
    (or that would be, under ``dry_run``).
    """
    from .models import NewsSource, NewsTopic
    from .topics import TOPICS

    stats = {
        'sources_created': 0,
        'topics_created': 0,
        'topics_updated': 0,
    }
    for feed in NEWS_FEEDS:
        slug = feed['slug']
        defaults = {k: v for k, v in feed.items() if k != 'slug'}
        if dry_run:
            if not NewsSource.objects.filter(slug=slug).exists():
                stats['sources_created'] += 1
            continue
        _, created = NewsSource.objects.get_or_create(
            slug=slug, defaults=defaults,
        )
        if created:
            stats['sources_created'] += 1
    for topic in TOPICS:
        slug = topic['slug']
        defaults = {k: v for k, v in topic.items() if k != 'slug'}
        if dry_run:
            row = NewsTopic.objects.filter(slug=slug).first()
            if row is None:
                stats['topics_created'] += 1
            elif sync and (
                row.keywords != defaults['keywords']
                or row.weight != defaults['weight']
            ):
                stats['topics_updated'] += 1
            continue
        row, created = NewsTopic.objects.get_or_create(
            slug=slug, defaults=defaults,
        )
        if created:
            stats['topics_created'] += 1
        elif sync and (
            row.keywords != defaults['keywords']
            or row.weight != defaults['weight']
        ):
            row.keywords = defaults['keywords']
            row.weight = defaults['weight']
            row.save(update_fields=['keywords', 'weight'])
            stats['topics_updated'] += 1
    return stats

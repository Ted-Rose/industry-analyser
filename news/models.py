"""News app models — RSS articles, topic classification, story
clusters and the daily digest (docs/plans/news_digest_plan.md)."""
from django.db import models


class NewsSource(models.Model):
    """One RSS feed of a Latvian news outlet."""

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    feed_url = models.URLField()
    language = models.CharField(max_length=8, default='lv')
    is_enabled = models.BooleanField(default=True)
    # 'tag' = <category> elements, 'url' = link path segments,
    # 'none' = the feed carries no usable category signal.
    category_strategy = models.CharField(max_length=8, default='none')
    importance_weight = models.FloatField(default=1.0)

    class Meta:
        db_table = 'news_source'

    def __str__(self):
        return f'{self.name} ({self.slug})'


class NewsTopic(models.Model):
    """User-interest topic matched by Latvian keyword rules."""

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    # List of Latvian keyword strings matched against title +
    # lead — per-word markers: '=word' exact token, 'word*'
    # token prefix, plain word = 4-char stem (see
    # news.classification / news.topics).
    keywords = models.JSONField(default=list)
    weight = models.FloatField(default=1.0)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'news_topic'

    def __str__(self):
        return f'{self.name} ({self.slug})'


class NewsStory(models.Model):
    """A cluster of articles from different outlets covering the
    same story."""

    title = models.CharField(max_length=500)
    representative_lead = models.TextField(blank=True)
    topic = models.ForeignKey(
        NewsTopic,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    published_date = models.DateField(db_index=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    source_count = models.PositiveIntegerField(default=0)
    importance_score = models.FloatField(default=0)

    class Meta:
        db_table = 'news_story'

    def __str__(self):
        return self.title


# story_match_status values that count as confirmed story
# coverage — 'candidate' links await admin review and must not
# inflate source_count, the digest rationale or the rendered
# digest page.
CONFIRMED_MATCH_STATUSES = ('auto', 'manual')


class NewsArticle(models.Model):
    """One RSS feed item from one source."""

    MATCH_STATUSES = [
        ('unmatched', 'Unmatched'),
        ('auto', 'Auto-linked'),
        ('candidate', 'Pending review'),
        ('manual', 'Manually linked'),
    ]

    source = models.ForeignKey(
        NewsSource,
        on_delete=models.CASCADE,
        related_name='articles',
    )
    # guid text, else sha256(link)[:32]
    external_id = models.CharField(max_length=64)
    link = models.URLField(max_length=600)
    title = models.CharField(max_length=500)
    lead = models.TextField(blank=True)
    image_url = models.URLField(max_length=600, blank=True)
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )
    feed_categories = models.JSONField(default=list, blank=True)
    topic = models.ForeignKey(
        NewsTopic,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    story = models.ForeignKey(
        NewsStory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='articles',
    )
    story_match_status = models.CharField(
        max_length=16,
        choices=MATCH_STATUSES,
        default='unmatched',
        db_index=True,
    )
    story_match_score = models.FloatField(null=True, blank=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'news_article'
        unique_together = [('source', 'external_id')]

    def __str__(self):
        return self.title


class NewsDigest(models.Model):
    """One day's ranked digest of top unique stories."""

    date = models.DateField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'news_digest'

    def __str__(self):
        return f'Digest {self.date}'


class NewsDigestItem(models.Model):
    """One ranked story inside a digest."""

    digest = models.ForeignKey(
        NewsDigest,
        on_delete=models.CASCADE,
        related_name='items',
    )
    story = models.ForeignKey(NewsStory, on_delete=models.CASCADE)
    rank = models.PositiveSmallIntegerField()
    headline = models.CharField(max_length=500)
    rationale = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = 'news_digest_item'
        unique_together = [('digest', 'rank'), ('digest', 'story')]

    def __str__(self):
        return f'#{self.rank} {self.headline}'

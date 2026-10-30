"""News app models — RSS articles, topic classification, story
clusters and the daily digest (docs/plans/news_digest_plan.md)."""
from django.conf import settings
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
    # HTTP validators from the last 200 response — sent back as
    # If-None-Match / If-Modified-Since so an unchanged feed
    # answers 304 and skips parsing entirely.
    etag = models.CharField(max_length=200, null=True, blank=True)
    last_modified = models.CharField(
        max_length=200, null=True, blank=True
    )

    class Meta:
        db_table = 'news_source'

    def save(self, *args, **kwargs):
        # The stored validators describe the previous feed_url —
        # a different resource can legitimately answer 304 to
        # them and then never be re-parsed, so a feed_url edit
        # drops them and the next poll is unconditional.
        update_fields = kwargs.get('update_fields')
        if self.pk is not None and (
            update_fields is None or 'feed_url' in update_fields
        ):
            old_url = (
                NewsSource.objects.filter(pk=self.pk)
                .values_list('feed_url', flat=True)
                .first()
            )
            if old_url is not None and old_url != self.feed_url:
                self.etag = None
                self.last_modified = None
                if update_fields is not None:
                    kwargs['update_fields'] = set(
                        update_fields
                    ) | {'etag', 'last_modified'}
        super().save(*args, **kwargs)

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


class NewsSourcePreference(models.Model):
    """A user's ranked favorite news outlets — rank 1 is tried
    first when picking which member article a story shows."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='news_source_preferences',
    )
    source = models.ForeignKey(
        NewsSource,
        on_delete=models.CASCADE,
        related_name='user_preferences',
    )
    rank = models.PositiveSmallIntegerField()

    class Meta:
        db_table = 'news_source_preference'
        unique_together = (('user', 'source'),)
        ordering = ('rank',)

    def __str__(self):
        return f'{self.user}:{self.rank}:{self.source}'


class NewsArticleAudio(models.Model):
    """Audio seam for a future TTS feature — one rendered
    narration of an article's spoken text per engine+voice.
    No generator exists yet; the table and endpoint are the
    contract it will fill."""
    STATUSES = [
        ('pending', 'Pending'),
        ('ready', 'Ready'),
        ('failed', 'Failed'),
    ]
    article = models.ForeignKey(
        NewsArticle, on_delete=models.CASCADE,
        related_name='audio',
    )
    engine = models.CharField(max_length=32)
    voice = models.CharField(max_length=64, blank=True)
    text = models.TextField()
    text_sha256 = models.CharField(max_length=64)
    status = models.CharField(
        max_length=8, choices=STATUSES,
        default='pending', db_index=True,
    )
    file_path = models.CharField(max_length=300, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'news_article_audio'
        unique_together = (('article', 'engine', 'voice'),)

    def __str__(self):
        return f'{self.article_id}:{self.engine}:{self.status}'

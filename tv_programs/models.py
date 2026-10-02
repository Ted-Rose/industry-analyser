from django.conf import settings
from django.db import models
import uuid


class Channel(models.Model):
    """Model representing a TV channel"""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)
    logo_url = models.URLField(max_length=200, null=True, blank=True)
    should_scrape = models.BooleanField(
        default=True,
        help_text="Whether this channel should be included in scraping"
    )

    def __str__(self):
        return self.name


class Category(models.Model):
    """Model representing a TV program category (e.g., News, Sports, Movie)"""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Categories"


class Program(models.Model):
    """Model representing a TV program"""

    class ContentType(models.TextChoices):
        MOVIE = "movie", "Movie"
        NOT_MOVIE = "not_movie", "Not a movie"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title_lv = models.CharField(max_length=500)
    title_eng = models.CharField(max_length=500, blank=True, null=True)
    description_lv = models.TextField(blank=True, null=True)
    description_eng = models.TextField(blank=True, null=True)
    # TODO: Consider adding index also for imdb_rating
    imdb_rating = models.CharField(max_length=50, blank=True, null=True)
    pg_rating = models.CharField(max_length=50, blank=True, null=True)
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name='programs'
    )
    categories = models.ManyToManyField(Category, through='ProgramCategory')
    start_time = models.DateTimeField()
    duration_minutes = models.IntegerField(null=True, blank=True)
    url = models.URLField(max_length=200, null=True, blank=True)
    image_url = models.URLField(blank=True, null=True)
    title_match_ratio = models.FloatField(default=0)
    description_match_ratio = models.FloatField(default=0)
    combined_match_ratio = models.FloatField(default=0)
    content_type = models.CharField(
        max_length=20,
        choices=ContentType.choices,
        default=ContentType.UNKNOWN,
        db_index=True,
    )
    classification_confidence = models.FloatField(default=0.0)
    classification_reasoning = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Which rule fired, e.g. title contains a seriāls keyword.",
    )
    tmdb_id = models.CharField(max_length=20, blank=True, null=True)
    imdb_id = models.CharField(max_length=20, blank=True, null=True)
    enrichment_source = models.CharField(max_length=20, blank=True, null=True)
    show = models.ForeignKey(
        'Show',
        on_delete=models.PROTECT,
        related_name='airings',
        null=True,
        blank=True,
    )
    source_event_id = models.CharField(
        max_length=30, unique=True, null=True, blank=True,
        help_text="tet.lv per-airing event id (show-expander data-id)",
    )

    class Meta:
        indexes = [
            models.Index(fields=['pg_rating', 'start_time']),
        ]
        unique_together = (('show', 'channel', 'start_time'),)

    def __str__(self):
        return f"{self.title_lv} ({self.channel.name})"


class ProgramCategory(models.Model):
    """Intermediary model for Program-Category many-to-many relationship"""
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)

    class Meta:
        unique_together = (('program', 'category'),)
        db_table = 'tv_programs_program_categories'


class Show(models.Model):
    """Canonical content row — one per unique title/description/episode.

    ``Program`` rows are airings that reference a Show; the same movie
    or episode airing repeatedly maps to a single Show. Identity is the
    ``dedup_key`` (sha256 over normalized title, normalized description,
    season and episode — see ``tv_programs.dedup``).
    """

    class EnrichmentStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ENRICHED = 'enriched', 'Enriched'
        NOT_FOUND = 'not_found', 'Not found'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    title_lv = models.CharField(max_length=500)  # normalized
    series_title = models.CharField(max_length=500, blank=True)
    series_season = models.IntegerField(null=True, blank=True)
    series_episode = models.IntegerField(null=True, blank=True)
    description_lv = models.TextField(blank=True, null=True)
    dedup_key = models.CharField(
        max_length=64, unique=True, db_index=True
    )
    title_eng = models.CharField(max_length=500, blank=True, null=True)
    description_eng = models.TextField(blank=True, null=True)
    year = models.CharField(max_length=10, blank=True, null=True)
    imdb_id = models.CharField(
        max_length=20, blank=True, null=True, db_index=True
    )
    imdb_url = models.URLField(max_length=200, blank=True, null=True)
    imdb_rating = models.DecimalField(
        max_digits=3, decimal_places=1, null=True, blank=True
    )
    pg_rating = models.CharField(max_length=50, blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    categories = models.ManyToManyField(Category, blank=True)
    content_type = models.CharField(
        max_length=20,
        choices=Program.ContentType.choices,
        default=Program.ContentType.UNKNOWN,
        db_index=True,
    )
    classification_confidence = models.FloatField(default=0.0)
    classification_reasoning = models.CharField(
        max_length=255, blank=True, null=True
    )
    enrichment_status = models.CharField(
        max_length=20,
        choices=EnrichmentStatus.choices,
        default=EnrichmentStatus.PENDING,
        db_index=True,
    )
    enrichment_source = models.CharField(
        max_length=20, blank=True, null=True  # 'omdb' | 'cinemeta'
    )
    enriched_at = models.DateTimeField(null=True, blank=True)
    title_match_ratio = models.FloatField(default=0)
    is_excluded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tv_programs_show'

    def __str__(self):
        return self.title_lv


class ShowPreference(models.Model):
    """Single-user like/dislike on a Show; ``user`` is null for the
    anonymous owner until auth lands."""

    class Reaction(models.TextChoices):
        LIKE = 'like', 'Like'
        DISLIKE = 'dislike', 'Dislike'

    show = models.ForeignKey(
        Show, on_delete=models.CASCADE, related_name='preferences'
    )
    reaction = models.CharField(max_length=10, choices=Reaction.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tv_programs_show_preference'
        unique_together = (('show', 'user'),)

    def __str__(self):
        return f"{self.reaction}: {self.show.title_lv}"

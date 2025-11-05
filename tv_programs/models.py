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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title_lv = models.CharField(max_length=500)
    title_eng = models.CharField(max_length=500)
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
    duration_minutes = models.IntegerField()
    url = models.URLField(max_length=200, null=True, blank=True)
    image_url = models.URLField(blank=True, null=True)
    title_match_ratio = models.FloatField(default=0)
    description_match_ratio = models.FloatField(default=0)
    combined_match_ratio = models.FloatField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=['pg_rating', 'start_time']),
        ]

    def __str__(self):
        return f"{self.title_lv} ({self.channel.name})"


class ProgramCategory(models.Model):
    """Intermediary model for Program-Category many-to-many relationship"""
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)

    class Meta:
        unique_together = (('program', 'category'),)
        db_table = 'tv_programs_program_categories'

from django.db import models
from django.contrib.auth import get_user_model


class Theme(models.Model):
    name = models.CharField(max_length=100, unique=True)
    analysis_order = models.IntegerField(
        default=0,
        help_text="Order in which this theme is analyzed (lower = first)"
    )

    class Meta:
        ordering = ['analysis_order', 'name']

    def __str__(self):
        return self.name


class Page(models.Model):
    title = models.CharField(max_length=200)
    url = models.URLField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    themes = models.ManyToManyField(Theme, through='PageAnalysis')

    has_video = models.BooleanField(
        default=False,
        help_text="Page contains video content or mentions video"
    )
    video_count = models.IntegerField(
        default=0,
        help_text="Number of video embeds detected"
    )
    image_count = models.IntegerField(
        default=0,
        help_text="Number of images in the page"
    )
    text_length = models.IntegerField(
        default=0,
        help_text="Length of text content in characters"
    )

    @property
    def is_media_heavy(self):
        """
        Calculate if page is media-heavy based on content.
        Media-heavy = has video OR (5+ images AND <1000 chars text)
        """
        return (
            self.has_video or
            (self.image_count >= 5 and self.text_length < 1000)
        )

    def __str__(self):
        return self.title


class PageAnalysis(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE)
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE)
    confidence_score = models.FloatField()
    reasoning_summary = models.TextField()
    theme_match = models.BooleanField()
    model = models.CharField(max_length=100)

    class Meta:
        unique_together = ('page', 'theme')

    def __str__(self):
        return f"{self.page.title} - {self.theme.name}"


class PageAnalysisReviews(models.Model):
    page_analysis = models.ForeignKey(PageAnalysis, on_delete=models.CASCADE)
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    analysis_approved = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.page_analysis} - {self.user}"

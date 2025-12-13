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


class PageManager(models.Manager):

    def kid_friendly(self):
        """
        Return kid-friendly pages:
        
        1. Pages where ALL expensive model analyses returned False
           AND no reviews have analysis_approved=False, OR
        2. Pages where kid_unfriendly=True but reviewer rejected it
        
        EXCLUDES:
        - Media-heavy pages (has_video OR 5+ images) AND <1000 chars
        """
        from django.db.models import Count, Q, Exists, OuterRef
        theme_count = Theme.objects.count()

        # Subquery: Check if page has any rejected reviews
        has_rejected_reviews = PageAnalysisReviews.objects.filter(
            page_analysis__page=OuterRef('pk'),
            analysis_approved=False
        )

        # Subquery: kid_unfriendly was True but reviewer rejected it
        kid_unfriendly_overridden = PageAnalysisReviews.objects.filter(
            page_analysis__page=OuterRef('pk'),
            page_analysis__theme__name='kid_unfriendly',
            page_analysis__theme_match=True,
            analysis_approved=False
        )

        return self.annotate(
            # Count expensive model analyses with theme_match=False
            expensive_false_count=Count(
                'pageanalysis',
                filter=Q(
                    pageanalysis__model_tier='expensive',
                    pageanalysis__theme_match=False
                )
            ),
            has_rejected_reviews=Exists(has_rejected_reviews),
            kid_unfriendly_overridden=Exists(kid_unfriendly_overridden)
        ).filter(
            Q(
                # Condition 1: All expensive analyses are False
                # AND no rejected reviews
                expensive_false_count=theme_count,
                has_rejected_reviews=False
            ) |
            Q(
                # Condition 2: kid_unfriendly override
                kid_unfriendly_overridden=True
            )
        ).distinct()


class Page(models.Model):
    title = models.CharField(max_length=200)
    url = models.URLField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    themes = models.ManyToManyField(Theme, through='PageAnalysis')

    objects = PageManager()

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
            (self.has_video or self.image_count >= 5) and
            self.text_length < 1000
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
    model_tier = models.CharField(
        max_length=20,
        choices=[
            ('cheap', 'Cheap/Rough Model'),
            ('expensive', 'Expensive/Precise Model')
        ],
        default='expensive',
        help_text="Tier of model used for analysis"
    )

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

from django.db import models


class Theme(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Page(models.Model):
    title = models.CharField(max_length=200)
    url = models.URLField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    themes = models.ManyToManyField(Theme, through='PageAnalysis')

    def __str__(self):
        return self.title


class PageAnalysis(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE)
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE)
    confidence_score = models.FloatField()
    reasoning_summary = models.TextField()

    class Meta:
        unique_together = ('page', 'theme')

    def __str__(self):
        return f"{self.post.title} - {self.theme.name}"

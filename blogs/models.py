from django.db import models


class Post(models.Model):
    title = models.CharField(max_length=200)
    url = models.URLField(max_length=200, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

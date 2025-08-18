from django.db import models
import uuid
from django.utils import timezone

class Channel(models.Model):
    """Model representing a TV channel"""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)
    url = models.URLField(max_length=200, null=True, blank=True)
    logo_url = models.URLField(max_length=200, null=True, blank=True)
    
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
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='programs')
    categories = models.ManyToManyField(Category, through='ProgramCategory')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    duration_minutes = models.IntegerField()
    url = models.URLField(max_length=200, null=True, blank=True)
    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    program_portal_id = models.CharField(max_length=100, null=True, blank=True)
    
    def __str__(self):
        return f"{self.title} ({self.channel.name})"
    
    def save(self, *args, **kwargs):
        # Calculate duration if not provided
        if not self.duration_minutes and self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            self.duration_minutes = delta.seconds // 60
        super().save(*args, **kwargs)

class ProgramCategory(models.Model):
    """Intermediary model for Program-Category many-to-many relationship"""
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    
    class Meta:
        unique_together = (('program', 'category'),)
        db_table = 'tv_programs_program_categories'

class Keyword(models.Model):
    """Model representing keywords for TV programs"""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)
    only_filter = models.BooleanField(default=False)
    added = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        self.name = self.name.lower()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name

class ProgramContainsKeyword(models.Model):
    """Intermediary model for Program-Keyword relationship"""
    id = models.AutoField(primary_key=True)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE)
    
    class Meta:
        db_table = 'tv_programs_program_contains_keyword'
        unique_together = (('program', 'keyword'),)

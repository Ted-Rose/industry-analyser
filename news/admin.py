from django import forms
from django.contrib import admin
from django.db import models

from .models import (
    NewsArticle,
    NewsDigest,
    NewsDigestItem,
    NewsSource,
    NewsStory,
    NewsTopic,
)


@admin.register(NewsSource)
class NewsSourceAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'slug', 'language', 'is_enabled',
        'importance_weight',
    )
    list_editable = ('is_enabled',)
    list_filter = ('language', 'is_enabled')


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'source', 'topic', 'published_at',
        'story_match_status',
    )
    list_filter = (
        'source', 'topic', 'story_match_status', 'published_at',
    )
    search_fields = ('title', 'link')
    readonly_fields = ('first_seen', 'last_seen')


class NewsArticleInline(admin.TabularInline):
    """Read-only member articles on the NewsStory page."""
    model = NewsArticle
    extra = 0
    can_delete = False
    show_change_link = True
    fields = (
        'title', 'source', 'published_at', 'story_match_status',
        'story_match_score',
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(NewsStory)
class NewsStoryAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'topic', 'published_date', 'source_count',
        'importance_score',
    )
    list_filter = ('topic', 'published_date')
    search_fields = ('title',)
    inlines = [NewsArticleInline]


@admin.register(NewsTopic)
class NewsTopicAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'weight', 'is_enabled')
    # Keywords list edited as a JSON textarea.
    formfield_overrides = {
        models.JSONField: {
            'widget': forms.Textarea(attrs={'rows': 10, 'cols': 60})
        },
    }


class NewsDigestItemInline(admin.TabularInline):
    model = NewsDigestItem
    extra = 0
    fields = ('rank', 'headline', 'rationale', 'story')
    autocomplete_fields = ('story',)


@admin.register(NewsDigest)
class NewsDigestAdmin(admin.ModelAdmin):
    list_display = ('date', 'created_at')
    inlines = [NewsDigestItemInline]

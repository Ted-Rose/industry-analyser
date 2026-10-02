from django.contrib import admin

from .models import Category, Channel, Program, Show, ShowPreference


@admin.register(Show)
class ShowAdmin(admin.ModelAdmin):
    list_display = (
        'title_lv', 'series_title', 'series_season', 'series_episode',
        'content_type', 'enrichment_status', 'imdb_rating',
        'is_excluded', 'created_at',
    )
    list_filter = ('enrichment_status', 'content_type', 'is_excluded')
    search_fields = (
        'title_lv', 'series_title', 'title_eng', 'imdb_id'
    )
    readonly_fields = ('dedup_key', 'enriched_at', 'created_at')


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = (
        'title_lv', 'channel', 'start_time', 'show',
        'source_event_id',
    )
    list_filter = ('channel',)
    search_fields = ('title_lv', 'source_event_id')
    raw_id_fields = ('show',)


@admin.register(ShowPreference)
class ShowPreferenceAdmin(admin.ModelAdmin):
    list_display = ('show', 'reaction', 'user', 'created_at')
    list_filter = ('reaction',)
    raw_id_fields = ('show',)


admin.site.register(Channel)
admin.site.register(Category)

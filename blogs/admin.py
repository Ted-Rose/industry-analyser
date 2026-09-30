from django.contrib import admin

from .models import Page, Theme, PageAnalysis


admin.site.register(Page)
admin.site.register(Theme)


@admin.register(PageAnalysis)
class PageAnalysisAdmin(admin.ModelAdmin):
    list_display = (
        'page', 'theme', 'theme_match', 'confidence_score',
        'model', 'model_tier', 'ai_model',
    )
    list_select_related = ('page', 'theme', 'ai_model')

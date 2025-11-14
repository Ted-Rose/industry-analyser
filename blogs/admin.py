from django.contrib import admin

from .models import Page, Theme, PageAnalysis


admin.site.register(Page)
admin.site.register(Theme)
admin.site.register(PageAnalysis)

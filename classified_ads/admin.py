from django.contrib import admin

from .models import ClassifiedAd, ClassifiedAdSighting, Region


class ClassifiedAdSightingInline(admin.TabularInline):
    model = ClassifiedAdSighting
    extra = 0
    readonly_fields = ['seen_on']
    can_delete = False
    ordering = ['-seen_on']


@admin.register(ClassifiedAd)
class ClassifiedAdAdmin(admin.ModelAdmin):
    list_display = [
        'region_name', 'district', 'deal_type', 'rooms', 'size',
        'floor', 'project', 'total_price', 'post_date',
        'phone', 'days_active',
    ]
    list_filter = ['deal_type', 'region', 'district', 'project']
    search_fields = ['district', 'street_name', 'project', 'phone']
    ordering = ['-post_date']
    readonly_fields = ['first_seen', 'last_seen', 'days_active']
    inlines = [ClassifiedAdSightingInline]

    @admin.display(description='Days active')
    def days_active(self, obj):
        return obj.days_active


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ['name', 'parent', 'url', 'scrape_enabled']
    list_filter = ['scrape_enabled', 'parent']
    list_editable = ['scrape_enabled']
    search_fields = ['name', 'url']


@admin.register(ClassifiedAdSighting)
class ClassifiedAdSightingAdmin(admin.ModelAdmin):
    list_display = ['ad', 'seen_on']
    list_filter = ['seen_on']
    ordering = ['-seen_on']

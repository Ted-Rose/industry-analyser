import logging

from django.contrib import admin
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html

from . import usage
from .models import (
    ScrapeJob,
    ScrapeJobItem,
    ScrapeJobRun,
    ScrapeJobRunItem,
)

logger = logging.getLogger('scrape_jobs')


class ScrapeJobItemInline(admin.TabularInline):
    """Items on the job page: key/label are runtime-owned (read-only),
    priority/is_active are the admin knobs."""

    model = ScrapeJobItem
    extra = 0
    fields = ['key', 'label', 'priority', 'is_active']
    readonly_fields = ['key', 'label']


@admin.register(ScrapeJob)
class ScrapeJobAdmin(admin.ModelAdmin):
    list_display = [
        'slug',
        'is_enabled',
        'stale_timeout_minutes',
        'item_count',
        'last_run',
        'updated_at',
    ]
    list_filter = ['is_enabled']
    search_fields = ['slug', 'description']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [ScrapeJobItemInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            'items', 'runs'
        )

    @admin.display(description='Items')
    def item_count(self, obj):
        return len(obj.items.all())

    @admin.display(description='Last run')
    def last_run(self, obj):
        run = max(obj.runs.all(), key=lambda r: r.id, default=None)
        if run is None:
            return '—'
        url = (
            f'/admin/scrape_jobs/scrapejobrun/{run.pk}/change/'
        )
        return format_html(
            '<a href="{}">#{} {}</a>', url, run.pk, run.status
        )


@admin.register(ScrapeJobItem)
class ScrapeJobItemAdmin(admin.ModelAdmin):
    list_display = [
        'key', 'job', 'label', 'priority', 'is_active', 'updated_at',
    ]
    list_filter = ['job', 'is_active']
    list_editable = ['priority', 'is_active']
    search_fields = ['key', 'label']
    list_select_related = ['job']


class ScrapeJobRunItemInline(admin.TabularInline):
    model = ScrapeJobRunItem
    extra = 0
    fields = ['item', 'status', 'error_message', 'completed_at']
    readonly_fields = fields
    can_delete = False
    ordering = ['-completed_at']

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('item')


class ReadOnlyRunMixin:
    """Run/item rows are written by runtime code only."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ScrapeJobRun)
class ScrapeJobRunAdmin(ReadOnlyRunMixin, admin.ModelAdmin):
    change_list_template = (
        'admin/scrape_jobs/scrapejobrun/change_list.html'
    )
    list_display = [
        'id',
        'job',
        'cycle_key',
        'status',
        'executed_by',
        'execution_id',
        'last_completed_item',
        'duration',
        'started_at',
        'updated_at',
    ]
    list_filter = ['job', 'status', 'cycle_key', 'executed_by']
    date_hierarchy = 'started_at'
    list_select_related = ['job', 'last_completed_item']
    readonly_fields = [
        'job', 'cycle_key', 'execution_id', 'executed_by', 'status',
        'last_completed_item', 'error_message', 'started_at',
        'updated_at', 'completed_at', 'duration',
    ]
    inlines = [ScrapeJobRunItemInline]

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'usage/',
                self.admin_site.admin_view(self.usage_view),
                name='scrape_jobs_scrapejobrun_usage',
            ),
        ]
        return custom + urls

    def usage_view(self, request):
        """Day x job run aggregates with a date-range filter
        (default: last 30 days, ?from=&to= ISO dates)."""
        default_from, default_to = usage.default_date_range()
        date_from = usage.parse_date(request.GET.get('from'))
        date_to = usage.parse_date(request.GET.get('to'))
        if date_from is None:
            date_from = default_from
        if date_to is None:
            date_to = default_to
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Scrape run usage',
            'date_from': date_from,
            'date_to': date_to,
            'rows': usage.runs_by_day(date_from, date_to),
            'totals': usage.run_totals(date_from, date_to),
            'items': usage.item_totals(date_from, date_to),
        }
        return TemplateResponse(
            request,
            'admin/scrape_jobs/scrapejobrun/usage.html',
            context,
        )

    @admin.display(description='Duration')
    def duration(self, obj):
        if obj.completed_at is None:
            return '—'
        return obj.completed_at - obj.started_at


@admin.register(ScrapeJobRunItem)
class ScrapeJobRunItemAdmin(ReadOnlyRunMixin, admin.ModelAdmin):
    list_display = [
        'id', 'run', 'item_key', 'status', 'error_message',
        'completed_at',
    ]
    list_filter = ['status', 'run__job']
    list_select_related = ['run', 'run__job', 'item']

    @admin.display(description='Item')
    def item_key(self, obj):
        return obj.item.key

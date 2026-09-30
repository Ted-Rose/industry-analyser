from django.contrib import admin
from django.db.models import Count

from .forms import (
    AIJobModelInlineForm,
    AIJobModelInlineFormSet,
    AIProviderAdminForm,
)
from .models import (
    AIInput,
    AIJob,
    AIJobModel,
    AIModel,
    AIPromptTemplate,
    AIProvider,
    AIRequest,
)


@admin.register(AIProvider)
class AIProviderAdmin(admin.ModelAdmin):
    form = AIProviderAdminForm
    list_display = [
        'slug',
        'display_name',
        'provider_type',
        'is_enabled',
        'has_api_key',
        'base_url',
    ]

    @admin.display(boolean=True, description='Has API key')
    def has_api_key(self, obj):
        return obj.has_api_key


@admin.register(AIModel)
class AIModelAdmin(admin.ModelAdmin):
    list_display = [
        '__str__',
        'provider',
        'is_enabled',
        'auto_registered',
        'supports_json_mode',
        'input_price_per_mtok',
        'output_price_per_mtok',
        'last_used_at',
    ]
    list_editable = ['is_enabled']
    list_filter = ['provider', 'is_enabled', 'auto_registered']
    search_fields = ['name', 'display_name']
    readonly_fields = ['first_seen_at', 'last_used_at']
    list_select_related = ['provider']

    def get_search_results(self, request, queryset, search_term):
        """Autocomplete (used by the AIJob assignment inline) only
        offers enabled models."""
        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )
        match = request.resolver_match
        if match and match.url_name == 'autocomplete':
            queryset = queryset.filter(is_enabled=True)
        return queryset, use_distinct


class AIJobModelInline(admin.TabularInline):
    model = AIJobModel
    form = AIJobModelInlineForm
    formset = AIJobModelInlineFormSet
    autocomplete_fields = ['model']
    extra = 1

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'model__provider'
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'model':
            kwargs['queryset'] = AIModel.objects.filter(
                is_enabled=True
            ).select_related('provider')
        return super().formfield_for_foreignkey(
            db_field, request, **kwargs
        )


@admin.register(AIJob)
class AIJobAdmin(admin.ModelAdmin):
    list_display = [
        'slug',
        'is_enabled',
        'max_requests_per_run',
        'max_requests_per_day',
        'assignment_summary',
    ]
    readonly_fields = ['declared_roles', 'description']
    inlines = [AIJobModelInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            'assignments__model__provider'
        )

    @admin.display(description='Assignments')
    def assignment_summary(self, obj):
        parts = [
            f'{a.role}: {a.model}' for a in obj.assignments.all()
        ]
        return ', '.join(parts) or '—'


class ReadOnlyAdminMixin:
    """Rows are written by runtime code only; the admin shows them
    read-only."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AIRequest)
class AIRequestAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        'created_at',
        'job',
        'role',
        'requested_model',
        'served_model',
        'status',
        'attempt',
        'tokens',
        'cost_usd',
        'latency_ms',
    ]
    list_filter = [
        'job',
        'status',
        'requested_model__provider',
        'prompt_layout',
    ]
    date_hierarchy = 'created_at'
    list_select_related = [
        'job',
        'requested_model__provider',
        'served_model',
    ]

    @admin.display(description='Tokens (in/out)')
    def tokens(self, obj):
        input_t = '—' if obj.input_tokens is None else obj.input_tokens
        output_t = '—' if obj.output_tokens is None else obj.output_tokens
        return f'{input_t} / {output_t}'


@admin.register(AIPromptTemplate)
class AIPromptTemplateAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        'key',
        'short_sha256',
        'first_seen_at',
        'request_count',
    ]
    list_filter = ['key']
    search_fields = ['key']

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            request_count=Count('requests')
        )

    @admin.display(description='SHA-256')
    def short_sha256(self, obj):
        return obj.sha256[:12]

    @admin.display(description='Requests', ordering='request_count')
    def request_count(self, obj):
        return obj.request_count


@admin.register(AIInput)
class AIInputAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['short_sha256', 'chars', 'created_at']
    search_fields = ['sha256']

    @admin.display(description='SHA-256')
    def short_sha256(self, obj):
        return obj.sha256[:12]

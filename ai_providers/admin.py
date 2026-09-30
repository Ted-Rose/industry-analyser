import logging

from django.conf import settings
from django.contrib import admin, messages
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from .catalog import sync_provider_models
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

logger = logging.getLogger('ai_providers')


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
    actions = ['sync_model_catalog']

    @admin.display(boolean=True, description='Has API key')
    def has_api_key(self, obj):
        return obj.has_api_key

    @admin.action(description='Sync model catalog')
    def sync_model_catalog(self, request, queryset):
        """Pull each provider's free model-listing endpoint and
        reconcile the ai_model table (PR-5). A failure on one
        provider is reported but does not stop the others."""
        for provider in queryset:
            try:
                counts = sync_provider_models(provider)
            except Exception as e:  # noqa: BLE001 — isolate failures
                key = getattr(settings, provider.api_key_setting, '')
                message = str(e)
                if key:
                    message = message.replace(key, '<redacted>')
                logger.warning(
                    'Model catalog sync failed for %s: %s',
                    provider.slug, message,
                )
                self.message_user(
                    request,
                    f'{provider.slug}: catalog sync failed: '
                    f'{message}',
                    level=messages.ERROR,
                )
                continue
            self.message_user(
                request,
                f"{provider.slug}: model catalog synced — "
                f"{counts['created']} created, "
                f"{counts['updated']} updated, "
                f"{counts['skipped']} skipped.",
                level=messages.SUCCESS,
            )


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


def _admin_obj_link(obj):
    """Link to an object's admin page (change view renders read-only
    for view-only users), or an em dash for null."""
    if obj is None:
        return '—'
    url = reverse(
        f'admin:{obj._meta.app_label}_{obj._meta.model_name}_change',
        args=[obj.pk],
    )
    return format_html('<a href="{}">{}</a>', url, obj)


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
    # The two prompt FKs are excluded so the detail page shows the
    # admin links below instead of disabled select widgets.
    exclude = ['prompt_template', 'input']
    readonly_fields = [
        'created_at',
        'job',
        'role',
        'requested_model',
        'served_model',
        'attempt',
        'status',
        'error_type',
        'error_message',
        'http_status',
        'finish_reason',
        'block_reason',
        'input_tokens',
        'output_tokens',
        'cost_usd',
        'latency_ms',
        'prompt_template_link',
        'input_link',
        'prompt_layout',
        'options',
        'prompt_chars',
        'prompt_sha256',
        'response_text',
        'rendered_prompt_display',
    ]

    @admin.display(description='Tokens (in/out)')
    def tokens(self, obj):
        input_t = '—' if obj.input_tokens is None else obj.input_tokens
        output_t = '—' if obj.output_tokens is None else obj.output_tokens
        return f'{input_t} / {output_t}'

    @admin.display(description='Prompt template')
    def prompt_template_link(self, obj):
        return _admin_obj_link(obj.prompt_template)

    @admin.display(description='Input')
    def input_link(self, obj):
        return _admin_obj_link(obj.input)

    @admin.display(description='Rendered prompt')
    def rendered_prompt_display(self, obj):
        """The exact prompt sent, rebuilt and hash-verified by
        AIRequest.rendered_prompt()."""
        rendered = obj.rendered_prompt()
        if rendered is None:
            return '—'
        sections = []
        if rendered.system is not None:
            sections.append(f'--- system ---\n{rendered.system}')
        sections.append(f'--- user ---\n{rendered.user}')
        return format_html(
            '<pre style="margin:0; white-space:pre-wrap; '
            'font-family:monospace;">{}</pre>',
            '\n\n'.join(sections),
        )


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

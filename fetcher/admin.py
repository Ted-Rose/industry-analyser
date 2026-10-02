from django.contrib import admin, messages
from django.db.models import Count
from django.template.response import TemplateResponse

from .company_linking import merge_companies
from .models import Company, CompanyAlias, CompanyIdentity


class CompanyIdentityInline(admin.TabularInline):
    model = CompanyIdentity
    extra = 0
    can_delete = False
    readonly_fields = [
        'source', 'employer_id', 'first_seen', 'last_seen',
    ]

    def has_add_permission(self, request, obj=None):
        return False


class CompanyAliasInline(admin.TabularInline):
    model = CompanyAlias
    extra = 0
    can_delete = False
    ordering = ['kind', 'value']
    readonly_fields = [
        'kind', 'value', 'first_seen', 'last_seen',
    ]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'reg_code', 'identity_sources', 'vacancy_count',
        'needs_review', 'merged_into', 'last_seen',
    ]
    list_filter = ['needs_review']
    search_fields = ['name', 'reg_code', 'aliases__value']
    readonly_fields = [
        'first_seen', 'last_seen', 'detail_fetched_at',
        'raw_employer',
    ]
    raw_id_fields = ['merged_into']
    inlines = [CompanyIdentityInline, CompanyAliasInline]
    actions = ['merge_companies_action']
    show_full_result_count = False

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .annotate(vacancy_total=Count('vacancies', distinct=True))
            .prefetch_related('identities')
        )

    @admin.display(description='Identities')
    def identity_sources(self, obj):
        return ', '.join(
            f'{i.source}:{i.employer_id}'
            for i in obj.identities.all()
        )

    @admin.display(description='Vacancies', ordering='vacancy_total')
    def vacancy_count(self, obj):
        return obj.vacancy_total

    @admin.action(
        description='Merge selected companies into one…'
    )
    def merge_companies_action(self, request, queryset):
        """Intermediate-page action: repoint identities, vacancies
        and aliases to the chosen survivor, set ``merged_into`` on
        the losers, clear ``needs_review`` (the human looked)."""
        if request.POST.get('apply'):
            target = queryset.filter(
                pk=request.POST.get('target')
            ).first()
            if target is None:
                self.message_user(
                    request,
                    'Choose a merge target among the selected '
                    'companies.',
                    messages.ERROR,
                )
                return
            losers = list(queryset.exclude(pk=target.pk))
            if not losers:
                self.message_user(
                    request,
                    'Nothing to merge — only the target was '
                    'selected.',
                    messages.WARNING,
                )
                return
            merge_companies(target, losers)
            self.message_user(
                request,
                f'Merged {len(losers)} company(ies) into '
                f'{target.name}.',
            )
            return
        selected = list(queryset)
        if len(selected) < 2:
            self.message_user(
                request,
                'Select at least two companies to merge.',
                messages.WARNING,
            )
            return
        return TemplateResponse(
            request,
            'admin/fetcher/company/merge.html',
            {
                **self.admin_site.each_context(request),
                'opts': self.model._meta,
                'title': 'Merge companies',
                'companies': selected,
                'selected_ids': [
                    str(pk) for pk in
                    queryset.values_list('pk', flat=True)
                ],
                'action_name': 'merge_companies_action',
            },
        )


@admin.register(CompanyIdentity)
class CompanyIdentityAdmin(admin.ModelAdmin):
    list_display = [
        'company', 'source', 'employer_id',
        'first_seen', 'last_seen',
    ]
    list_filter = ['source']
    search_fields = ['employer_id', 'company__name']
    readonly_fields = [
        'company', 'source', 'employer_id',
        'first_seen', 'last_seen',
    ]

    def has_add_permission(self, request):
        return False


@admin.register(CompanyAlias)
class CompanyAliasAdmin(admin.ModelAdmin):
    list_display = [
        'company', 'kind', 'value', 'first_seen', 'last_seen',
    ]
    list_filter = ['kind']
    search_fields = ['value', 'company__name']
    readonly_fields = [
        'company', 'kind', 'value', 'first_seen', 'last_seen',
    ]

    def has_add_permission(self, request):
        return False

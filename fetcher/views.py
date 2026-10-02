import logging
from django.shortcuts import get_object_or_404, render, redirect
from django.core.paginator import Paginator
from django.views.decorators.cache import cache_control
from .models import Company, Keyword, Vacancy, Industry
from .scraper import load_portals_config
from django.conf import settings
from django.utils import timezone
from django.db.models import Count, F, Q
from .forms import KeywordForm


logger = logging.getLogger('fetcher')


def home(request):
    return render(request, 'fetcher/home.html')


# Bump on every shipped frontend change (new SPA bundle, sw.js edit)
# to force clients off the old service-worker cache.
PWA_CACHE_VERSION = 'v2'


def pwa_manifest(request):
    return render(
        request,
        'fetcher/manifest.json',
        content_type='application/json',
    )


@cache_control(no_cache=True)
def pwa_service_worker(request):
    return render(
        request,
        'fetcher/sw.js',
        {'cache_version': PWA_CACHE_VERSION},
        content_type='application/javascript',
    )


def find_vacancies(request):
    keywords = Keyword.objects.all()
    industries = Industry.objects.all()

    include_keywords = request.GET.getlist('include_keywords')
    exclude_keywords = request.GET.getlist('exclude_keywords')
    include_industries = request.GET.getlist('include_industries')
    show_active_only = request.GET.get('show_active_only') == '1'

    vacancies = Vacancy.objects.filter(
        **{
            'industries__name__in': include_industries
        } if include_industries else {},
        **{
            'vacancycontainskeyword__keyword__name__in': include_keywords
        } if include_keywords else {}
    )

    if exclude_keywords:
        vacancies = vacancies.exclude(
            vacancycontainskeyword__keyword__name__in=exclude_keywords
        )

    if show_active_only:
        vacancies = vacancies.filter(
            application_deadline__gte=timezone.now()
        )

    vacancies = vacancies.distinct().order_by(
        F('application_deadline').desc(nulls_last=True), '-last_seen'
    )

    paginator = Paginator(vacancies, 300)
    page = request.GET.get('page')
    vacancies_page = paginator.get_page(page)

    query_dict = request.GET.copy()
    query_dict.pop('page', None)
    query_params = query_dict.urlencode()

    return render(request, 'fetcher/vacancies.html', {
        'vacancies': vacancies_page,
        'keywords': keywords,
        'industries': industries,
        'include_keywords': include_keywords,
        'exclude_keywords': exclude_keywords,
        'include_industries': include_industries,
        'show_active_only': show_active_only,
        'total_count': paginator.count,
        'query_params': query_params,
        'now': timezone.now(),
    })


def _file_url(file_id):
    """files-service URL for a stored file id (logo/cover/
    gallery), or None when no portal config provides files_href."""
    if not file_id:
        return None
    try:
        portals = load_portals_config()
    except Exception:
        return None
    for cfg in portals.values():
        if cfg.get('base_url') and cfg.get('files_href'):
            return cfg['base_url'] + cfg['files_href'] + file_id
    return None


def company_list(request):
    """Browsable list of canonical companies (merged-away rows
    hidden — their pages redirect to the survivor)."""
    now = timezone.now()
    companies = (
        Company.objects
        .filter(merged_into__isnull=True)
        .annotate(
            vacancy_count=Count('vacancies', distinct=True),
            open_count=Count(
                'vacancies', distinct=True,
                filter=Q(
                    vacancies__application_deadline__gte=now
                ),
            ),
        )
        .prefetch_related('identities')
        .order_by('name')
    )
    query = request.GET.get('q', '').strip()
    if query:
        companies = companies.filter(
            Q(name__icontains=query) | Q(reg_code__icontains=query)
        )
    paginator = Paginator(companies, 100)
    page = request.GET.get('page')
    return render(request, 'fetcher/companies.html', {
        'companies': paginator.get_page(page),
        'total_count': paginator.count,
        'query': query,
    })


def company_detail(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if company.merged_into_id is not None:
        return redirect(
            'company_detail', pk=company.canonical().pk
        )
    vacancies = (
        company.vacancies
        .all()
        .order_by(
            F('application_deadline').desc(nulls_last=True),
            '-last_seen',
        )
    )
    paginator = Paginator(vacancies, 100)
    page = request.GET.get('page')
    name_aliases = company.aliases.filter(kind='name')
    reg_aliases = company.aliases.filter(kind='reg_code')
    return render(request, 'fetcher/company_detail.html', {
        'company': company,
        'vacancies': paginator.get_page(page),
        'total_count': paginator.count,
        'logo_url': _file_url(company.logo_file_id),
        'cover_url': _file_url(company.cover_file_id),
        'gallery_urls': [
            _file_url(fid) for fid in (company.gallery or [])
        ],
        'name_aliases': name_aliases,
        'reg_aliases': reg_aliases,
        'now': timezone.now(),
    })


def add_keyword(request):
    hardcoded_password = settings.HARD_CODED_PASSWORD
    if hardcoded_password == "" or hardcoded_password is None:
        return render(request, 'fetcher/add_keyword.html', {
            'error': 'HARD_CODED_PASSWORD is not set.'
        })
    if request.method == 'POST':
        password = request.POST.get('password')

        if password != hardcoded_password:
            return render(request, 'fetcher/add_keyword.html', {
                'error': 'Invalid password.'
            })
        form = KeywordForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('find_vacancies')
    else:
        form = KeywordForm()
    return render(request, 'fetcher/add_keyword.html', {'form': form})

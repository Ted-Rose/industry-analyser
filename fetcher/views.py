import logging
from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from .models import Keyword, Vacancy, Industry
from django.conf import settings
from django.utils import timezone
from django.db.models import F
from .forms import KeywordForm


logger = logging.getLogger(__name__)

def home(request):
    return render(request, 'fetcher/home.html')


def pwa_manifest(request):
    return render(
        request,
        'fetcher/manifest.json',
        content_type='application/json',
    )


def pwa_service_worker(request):
    return render(
        request,
        'fetcher/sw.js',
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


def add_keyword(request):
    hardcoded_password = settings.HARD_CODED_PASSWORD
    if hardcoded_password == "" or hardcoded_password is None:
        return render(request, 'fetcher/add_keyword.html', {'error': 'HARD_CODED_PASSWORD is not set.'})
    if request.method == 'POST':
        name = request.POST.get('name')
        only_filter = request.POST.get('only_filter') == 'on'
        password = request.POST.get('password')

        if password != hardcoded_password:
            return render(request, 'fetcher/add_keyword.html', {'error': 'Invalid password.'})
        form = KeywordForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('find_vacancies')
    else:
        form = KeywordForm()
    return render(request, 'fetcher/add_keyword.html', {'form': form})

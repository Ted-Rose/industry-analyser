"""django-ninja router for the vacancies SPA (mounted at
/api/vacancies/ — the public URL base, not the app name).

GET ops are public (auth=None) — the template pages they replace
were public. POST /keywords/ keeps the default django_auth
(session + CSRF): a deliberate tightening vs. the retired
HARD_CODED_PASSWORD form (README §2 decision 2). Query logic
mirrors the retired views in fetcher/views.py — same filters,
same ordering, same per-page sizes.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Query, Router, Schema
from pydantic import Field

from industry_analyser.api import ApiHttpError

from .forms import KeywordForm
from .models import Company, Industry, Keyword, Vacancy
from .views import _file_url

router = Router()

# Same per-page sizes the template views used.
VACANCIES_PER_PAGE = 300
COMPANIES_PER_PAGE = 100


# --- Schemas ---


class VacancyOut(Schema):
    id: UUID
    title: Optional[str]
    url: str
    company_id: Optional[UUID]
    company_name: Optional[str]
    salary_from: Optional[float]
    salary_to: Optional[float]
    application_deadline: Optional[datetime]
    last_seen: Optional[datetime]
    days_open: Optional[int]
    keywords: List[str]
    industries: List[str]

    @staticmethod
    def resolve_keywords(obj):
        return [k.name for k in obj.keywords.all()]

    @staticmethod
    def resolve_industries(obj):
        return [i.name for i in obj.industries.all()]


class VacanciesOut(Schema):
    """One page of vacancies plus the filter option lists the page
    needs — a single fat endpoint per the rewrite plan."""
    vacancies: List[VacancyOut]
    page: int
    num_pages: int
    total_count: int
    start_index: int
    end_index: int
    has_next: bool
    has_previous: bool
    keywords: List[str]
    industries: List[str]


# Public URL of an employer identity on its portal. cv.lv has no
# public employer profile (GET /lv/employer/<id> → statusCode 401),
# so the link is the portal's vacancy search filtered to that
# employer — the closest public "company page" there is.
PORTAL_EMPLOYER_URLS = {
    'cv.lv': 'https://www.cv.lv/lv/search?employerId={employer_id}',
}


class CompanyIdentityOut(Schema):
    source: str
    employer_id: int
    portal_url: Optional[str]

    @staticmethod
    def resolve_portal_url(obj):
        template = PORTAL_EMPLOYER_URLS.get(obj.source)
        if template is None:
            return None
        return template.format(employer_id=obj.employer_id)


class CompanyOut(Schema):
    id: UUID
    name: str
    reg_code: Optional[str]
    about: Optional[str]
    webpage_url: Optional[str]
    needs_review: bool
    vacancy_count: int
    open_count: int
    last_seen: datetime
    identities: List[CompanyIdentityOut]

    @staticmethod
    def resolve_identities(obj):
        return obj.identities.all()


class CompaniesOut(Schema):
    companies: List[CompanyOut]
    page: int
    num_pages: int
    total_count: int
    start_index: int
    end_index: int
    has_next: bool
    has_previous: bool
    query: str


class CompanyVacancyOut(Schema):
    """Lean vacancy row for the company detail table — no M2M
    columns, matching the template's columns."""
    id: UUID
    title: Optional[str]
    url: str
    salary_from: Optional[float]
    salary_to: Optional[float]
    application_deadline: Optional[datetime]
    last_seen: Optional[datetime]


class CompanyDetailOut(Schema):
    id: UUID
    name: str
    reg_code: Optional[str]
    reg_code_country: Optional[str]
    about: Optional[str]
    webpage_url: Optional[str]
    video_url: Optional[str]
    applying_url: Optional[str]
    address: Optional[str]
    contact_name: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    needs_review: bool
    first_seen: datetime
    last_seen: datetime
    logo_url: Optional[str]
    cover_url: Optional[str]
    gallery_urls: List[Optional[str]]
    identities: List[CompanyIdentityOut]
    name_aliases: List[str]
    reg_aliases: List[str]
    vacancies: List[CompanyVacancyOut]
    page: int
    num_pages: int
    total_count: int
    start_index: int
    end_index: int
    has_next: bool
    has_previous: bool


class KeywordIn(Schema):
    name: str = Field(min_length=1, max_length=255)
    # The retired template form pre-checked "only filter" — keep that
    # as the default.
    only_filter: bool = True


class KeywordSavedOut(Schema):
    success: bool
    message: str


# --- Ops ---


@router.get('/', auth=None, response=VacanciesOut)
def list_vacancies(
    request,
    include_keywords: List[str] = Query([]),
    exclude_keywords: List[str] = Query([]),
    include_industries: List[str] = Query([]),
    show_active_only: bool = False,
    page: int = 1,
):
    """Vacancy list page payload — mirrors the retired
    find_vacancies view's filtering exactly."""
    vacancies = Vacancy.objects.filter(
        **{
            'industries__name__in': include_industries
        } if include_industries else {},
        **{
            'vacancycontainskeyword__keyword__name__in': (
                include_keywords
            )
        } if include_keywords else {},
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
    ).prefetch_related('keywords', 'industries')

    paginator = Paginator(vacancies, VACANCIES_PER_PAGE)
    vacancies_page = paginator.get_page(page)

    return VacanciesOut(
        vacancies=list(vacancies_page.object_list),
        page=vacancies_page.number,
        num_pages=paginator.num_pages,
        total_count=paginator.count,
        start_index=vacancies_page.start_index(),
        end_index=vacancies_page.end_index(),
        has_next=vacancies_page.has_next(),
        has_previous=vacancies_page.has_previous(),
        keywords=[
            k.name for k in Keyword.objects.order_by('name')
        ],
        industries=[
            i.name for i in Industry.objects.order_by('name')
        ],
    )


@router.get('/companies/', auth=None, response=CompaniesOut)
def list_companies(
    request,
    q: str = Query('', max_length=255),
    page: int = 1,
):
    """Company list — mirrors company_list: canonical companies
    only (merged-away rows hidden), name/reg-code search."""
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
    query = q.strip()
    if query:
        companies = companies.filter(
            Q(name__icontains=query) | Q(reg_code__icontains=query)
        )
    paginator = Paginator(companies, COMPANIES_PER_PAGE)
    companies_page = paginator.get_page(page)
    return CompaniesOut(
        companies=list(companies_page.object_list),
        page=companies_page.number,
        num_pages=paginator.num_pages,
        total_count=paginator.count,
        start_index=companies_page.start_index(),
        end_index=companies_page.end_index(),
        has_next=companies_page.has_next(),
        has_previous=companies_page.has_previous(),
        query=query,
    )


@router.get('/companies/{pk}/', auth=None, response=CompanyDetailOut)
def company_detail(request, pk: UUID, page: int = 1):
    """Company detail — mirrors the company_detail view. A merged
    company resolves to its canonical survivor (the old view 301'd
    there; the API returns the canonical record directly)."""
    company = get_object_or_404(Company, pk=pk)
    if company.merged_into_id is not None:
        company = company.canonical()
    vacancies = (
        company.vacancies
        .all()
        .order_by(
            F('application_deadline').desc(nulls_last=True),
            '-last_seen',
        )
    )
    paginator = Paginator(vacancies, COMPANIES_PER_PAGE)
    vacancies_page = paginator.get_page(page)
    return CompanyDetailOut(
        id=company.pk,
        name=company.name,
        reg_code=company.reg_code,
        reg_code_country=company.reg_code_country,
        about=company.about,
        webpage_url=company.webpage_url,
        video_url=company.video_url,
        applying_url=company.applying_url,
        address=company.address,
        contact_name=company.contact_name,
        contact_email=company.contact_email,
        contact_phone=company.contact_phone,
        needs_review=company.needs_review,
        first_seen=company.first_seen,
        last_seen=company.last_seen,
        logo_url=_file_url(company.logo_file_id),
        cover_url=_file_url(company.cover_file_id),
        gallery_urls=[
            _file_url(fid) for fid in (company.gallery or [])
        ],
        identities=list(company.identities.all()),
        name_aliases=[
            a.value for a in company.aliases.filter(kind='name')
        ],
        reg_aliases=[
            a.value for a in company.aliases.filter(kind='reg_code')
        ],
        vacancies=list(vacancies_page.object_list),
        page=vacancies_page.number,
        num_pages=paginator.num_pages,
        total_count=paginator.count,
        start_index=vacancies_page.start_index(),
        end_index=vacancies_page.end_index(),
        has_next=vacancies_page.has_next(),
        has_previous=vacancies_page.has_previous(),
    )


@router.post('/keywords/', response=KeywordSavedOut)
def add_keyword(request, payload: KeywordIn):
    """Create a keyword — session-auth replacement for the retired
    HARD_CODED_PASSWORD form. Validation still goes through
    KeywordForm so name normalization/uniqueness are unchanged."""
    form = KeywordForm(
        data={'name': payload.name, 'only_filter': payload.only_filter}
    )
    if not form.is_valid():
        detail = '; '.join(
            f'{field}: {" ".join(errors)}'
            for field, errors in form.errors.items()
        )
        raise ApiHttpError(400, detail, code='invalid_keyword')
    keyword = form.save()
    return KeywordSavedOut(
        success=True,
        message=f"Keyword '{keyword.name}' added.",
    )

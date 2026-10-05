import hashlib
import logging
import json
import os
import re
from django.conf import settings
from bs4 import BeautifulSoup
import urllib3
from . import company_linking
from .ai_jobs import VACANCY_IMAGE_OCR
from .models import (
    Company,
    CompanyAlias,
    CompanyIdentity,
    Industry,
    Keyword,
    Vacancy,
    VacancyContainsKeyword,
    VacancyFile,
    VacancyIndustries,
)
from typing import List
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ai_providers import errors as ai_errors
from ai_providers.client import get_job_client
from ai_providers.types import ImagePart, PromptSpec
from core_scraper.base import BaseScraper

logger = logging.getLogger('fetcher')

OCR_CONTENT_TYPES = ('image/', 'application/pdf')


def load_portals_config():
    """portal-id → config dict from FETCHER_PORTALS_JSON env or
    fetcher/config_v2.json."""
    portals_json = os.environ.get('FETCHER_PORTALS_JSON')
    if portals_json:
        return json.loads(portals_json)
    config_path = os.path.join(
        settings.BASE_DIR, 'fetcher/config_v2.json'
    )
    with open(config_path, 'r') as file:
        return json.load(file)['portals']


class VacancyScrapper(BaseScraper):
    def __init__(self, portal_id=1, runner=None, dry_run=False):
        super().__init__()
        self.runner = runner
        self.dry_run = dry_run
        self.portal_id = portal_id
        self.config = self.load_config(portal_id)
        self.keywords = Keyword.objects
        self.industries = Industry.objects
        # Cache keywords list for content matching optimization
        self.keywords_list = list(self.keywords.all())
        # Only nextjs portals have detail pages worth fetching;
        # API search results already carry the full payload.
        self.enrich_search_results = self.config.get('type') == 'nextjs'
        self.validate_result = False
        self.excluded_resources = []
        self._ai_client = None
        self._ocr_unavailable = False
        self._ocr_template = None
        self._detail_fetched_map = None
        self._search_total = None
        # Vacancy ids already processed this run — overlapping
        # search pages must not re-save the same rows.
        self._seen_ids = set()
        self._industry_cache = None
        # Detail-page enrichment counters — logged periodically so
        # Cloud Run logs show whether employer data (about etc.) is
        # being collected at all.
        self._detail_fetches = 0
        self._detail_skipped_fresh = 0
        self._detail_failed = 0
        self._detail_with_about = 0
        enrich = 'enabled' if self.enrich_search_results else 'OFF'
        logger.info(
            f"Portal {self.portal_id} "
            f"(type={self.config.get('type') or 'api'}) — "
            f"detail enrichment {enrich}"
        )

    def load_config(self, portal_id):
        return load_portals_config().get(str(portal_id))

    def get_search_urls(self):
        if self.config.get('search_params'):
            yield from self._sweep_search_urls()
            return
        yield from self._keyword_search_urls()

    def _keyword_search_urls(self):
        """Legacy API fallback when no ``search_params`` filter is
        configured: one search URL (and one checkpoint item) per
        keyword."""
        base_url = self.config['base_url'] + self.config['search_href']
        keywords = self.keywords.filter(
            only_filter=False
        ).order_by('id')
        if self.runner is None:
            for keyword in keywords:
                yield (
                    base_url
                    + f"?limit=1000&keywords[]={keyword.name}"
                )
            return
        items = self.runner.sync_items(
            (k.name, k.name, 0, k.name) for k in keywords
        )
        for item in self.runner.pending_items(items):
            try:
                yield (
                    base_url
                    + f"?limit=1000&keywords[]={item.obj}"
                )
                self.runner.touch()
            except Exception as e:
                self.runner.item_failed(item, e)
                continue
            self.runner.item_done(item)

    def _sweep_search_urls(self):
        """The whole offset-paginated ``search_params`` sweep is
        one checkpoint item (nextjs and API portals alike)."""
        if self.runner is None:
            yield from self._get_offset_search_urls()
            return
        base_url = self.config['base_url'] + self.config['search_href']
        items = self.runner.sync_items(
            [('search', base_url, 0, None)]
        )
        for item in self.runner.pending_items(items):
            try:
                for url in self._get_offset_search_urls():
                    yield url
                    self.runner.touch()
            except Exception as e:
                self.runner.item_failed(item, e)
                continue
            self.runner.item_done(item)

    def _get_offset_search_urls(self):
        """Offset-paginate ``search_params`` (e.g. an IT-category
        sweep) until a page comes back empty or ``total`` from the
        response — stored by ``parse_results`` — has been covered.
        """
        base_url = self.config['base_url'] + self.config['search_href']
        params = self.config['search_params']
        limit = int(self.config.get('page_size', 1000))
        offset = 0
        while True:
            yield (
                f"{base_url}?limit={limit}&offset={offset}&{params}"
            )
            total = self._search_total
            if not self.last_search_had_results:
                break
            offset += limit
            if total is not None and offset >= total:
                break

    def _extract_next_data(self, html):
        """Parse the Next.js ``__NEXT_DATA__`` JSON blob out of a
        server-rendered page; None when absent/invalid."""
        soup = BeautifulSoup(html, 'html.parser')
        tag = soup.find('script', id='__NEXT_DATA__')
        if tag is None or not tag.string:
            return None
        return self.parse_json(tag.string)

    def parse_results(
        self,
        search_response: urllib3.response.HTTPResponse
    ) -> List:
        if search_response is None:
            return []
        if self.config.get('type') == 'nextjs':
            data = self._extract_next_data(search_response.data)
            if not data:
                return []
            search = (
                data.get('props', {})
                .get('pageProps', {})
                .get('searchResults') or {}
            )
            self._search_total = search.get('total')
            return search.get('vacancies') or []
        content_type = search_response.headers.get('Content-Type', '')
        if 'application/json' not in content_type:
            logger.warning(
                f"Unexpected Content-Type {content_type!r} from "
                f"portal {self.portal_id} — expected JSON"
            )
            return []
        data = json.loads(search_response.data.decode('utf-8'))
        self._search_total = data.get('total')
        return data.get('vacancies', [])

    def remove_redundant_results(
      self,
      resources: List[Vacancy]
    ) -> List[Vacancy]:
        # Remove already processed vacancy id's in this session —
        # overlapping searches must not re-save the same rows.
        fresh = []
        for result in resources:
            result_id = result.get('id')
            if result_id is not None and result_id in self._seen_ids:
                continue
            self._seen_ids.add(result_id)
            fresh.append(result)
        return fresh

    def get_resource_info_link(self, result):
        return (
            self.config['base_url']
            + self.config['vacancy_base_href']
            + str(result.get('id'))
        )

    def enrich_result(self, result):
        """Fetch the public vacancy detail page and merge it into
        the search-result dict as ``result['_detail']``.

        Detail pages are only fetched for vacancies that are new or
        renewed since the last detail fetch (``detail_fetched_at``)
        — the search payload alone already carries everything the
        Vacancy model needs.
        """
        if not self._needs_detail_fetch(result):
            self._detail_skipped_fresh += 1
            return result
        info_link = self.get_resource_info_link(result)
        response = self.make_request(info_link)
        if response is None:
            self._detail_failed += 1
            logger.warning(
                f"Detail page fetch failed for vacancy "
                f"{result.get('id')}"
            )
            return result
        data = self._extract_next_data(response.data)
        detail = company_linking.extract_vacancy_detail(
            data, result['id']
        )
        if detail is None:
            self._detail_failed += 1
            logger.warning(
                f"No detail JSON for vacancy {result.get('id')} "
                f"at {info_link}"
            )
            return result
        self._detail_fetches += 1
        if (detail.get('employer') or {}).get('about'):
            self._detail_with_about += 1
        if self._detail_fetches % 25 == 0:
            logger.info(
                f"Detail enrichment progress: "
                f"{self._detail_fetches} fetched "
                f"({self._detail_with_about} with employer "
                f"'about'), {self._detail_skipped_fresh} "
                f"fresh-skipped, {self._detail_failed} failed"
            )
        enriched = dict(result)
        enriched['_detail'] = detail
        return enriched

    def _needs_detail_fetch(self, result) -> bool:
        vacancy_portal_id = result.get('id')
        if vacancy_portal_id is None:
            return False
        fetched_at = self._get_detail_fetched_map().get(
            vacancy_portal_id
        )
        if fetched_at is None:
            return True
        renewed = parse_datetime(
            result.get('renewedDate')
            or result.get('publishDate')
            or ''
        )
        return renewed is None or renewed > fetched_at

    def _get_detail_fetched_map(self):
        """{vacancy_portal_id: detail_fetched_at}, built lazily."""
        if self._detail_fetched_map is None:
            self._detail_fetched_map = dict(
                Vacancy.objects
                .exclude(detail_fetched_at__isnull=True)
                .exclude(vacancy_portal_id__isnull=True)
                .values_list('vacancy_portal_id', 'detail_fetched_at')
            )
        return self._detail_fetched_map

    @staticmethod
    def _standard_details_text(sections) -> str:
        """Flatten a detail page's standardDetails sections
        ({title, content-HTML}) into plain text."""
        parts = []
        for section in sections or []:
            content = section.get('content')
            if content:
                parts.append(
                    BeautifulSoup(content, 'html.parser')
                    .get_text(' ')
                )
        return ' '.join(parts)

    def _ocr_prompt(self):
        if self._ocr_template is None:
            path = os.path.join(
                settings.BASE_DIR, 'fetcher', 'prompts',
                'vacancy_ocr.txt',
            )
            with open(path, 'r', encoding='utf-8') as f:
                self._ocr_template = f.read()
        return self._ocr_template

    def _get_ai_client(self):
        if self._ai_client is None and not self._ocr_unavailable:
            try:
                self._ai_client = get_job_client(VACANCY_IMAGE_OCR)
            except ai_errors.AIError as e:
                logger.warning(
                    f"Vacancy OCR job unavailable, image files "
                    f"won't be transcribed this run: {e}"
                )
                self._ocr_unavailable = True
        return self._ai_client

    def _ocr_vacancy_file(self, file_id):
        """Return (extracted_text, unsaved VacancyFile | None) for a
        files-service file.

        Known file_ids reuse their stored text — each file is OCR'd
        once ever. On OCR failure (or a non-image/PDF file) the file
        row is not created, so the next run retries.
        """
        existing = VacancyFile.objects.filter(
            file_id=file_id
        ).first()
        if existing is not None:
            return existing.extracted_text or '', None
        if self._ocr_unavailable:
            return '', None
        file_url = (
            self.config['base_url']
            + self.config['files_href']
            + file_id
        )
        response = self.make_request(file_url)
        if response is None:
            return '', None
        content_type = (
            response.headers.get('Content-Type', '')
            .split(';')[0].strip()
        )
        if not content_type.startswith(OCR_CONTENT_TYPES):
            logger.info(
                f"Vacancy file {file_id} is {content_type}, "
                f"not OCR-able — skipping"
            )
            return '', None
        client = self._get_ai_client()
        if client is None:
            return '', None
        try:
            ai_result = client.generate(
                PromptSpec(
                    template_key='fetcher.vacancy_ocr',
                    template_text=self._ocr_prompt(),
                    input_text=f'{file_id} ({content_type})',
                    layout='system_v1',
                    images=(
                        ImagePart(
                            data=response.data,
                            mime_type=content_type,
                        ),
                    ),
                ),
                role='ocr',
            )
        except ai_errors.AIRequestCapReached as e:
            logger.warning(f"OCR request cap reached: {e}")
            self._ocr_unavailable = True
            return '', None
        except ai_errors.AIError as e:
            logger.warning(
                f"Vacancy file {file_id} OCR failed: {e}"
            )
            return '', None
        vacancy_file = VacancyFile(
            file_id=file_id,
            content_type=content_type,
            sha256=hashlib.sha256(response.data).hexdigest(),
            extracted_text=ai_result.text,
            ai_model=ai_result.served_model,
            ai_request=ai_result.ai_request,
        )
        return ai_result.text or '', vacancy_file

    def _extract_searchable_content(self, result: dict) -> str:
        """
        Extract and combine all searchable text from vacancy result.
        Returns lowercase string for case-insensitive matching.
        """
        content_parts = []

        # Add position title
        if result.get('positionTitle'):
            content_parts.append(result.get('positionTitle'))

        # Add position content (main description)
        if result.get('positionContent'):
            content_parts.append(result.get('positionContent'))

        # Add employer name
        if result.get('employerName'):
            content_parts.append(result.get('employerName'))

        # Add detail-page text / OCR'd file text when enriched
        if result.get('_extra_content'):
            content_parts.append(result['_extra_content'])

        # Combine and normalize
        combined_content = ' '.join(content_parts).lower()
        return combined_content

    def _find_keywords_in_content(
        self, content: str
    ) -> List[Keyword]:
        """
        Search for all keywords within content using regex.
        Uses word boundaries for accurate matching.
        """
        matched_keywords = []

        for keyword in self.keywords_list:
            # Use word boundary \b for accurate matching
            # re.escape handles special chars like C++, C#
            pattern = (
                r'\b' + re.escape(keyword.name.lower()) + r'\b'
            )
            if re.search(pattern, content):
                matched_keywords.append(keyword)

        return matched_keywords

    def _industry_named(self, name):
        """Industry row by name — the table is tiny, so it is
        cached once per run instead of queried per vacancy."""
        if self._industry_cache is None:
            self._industry_cache = {
                i.name: i for i in self.industries.all()
            }
        return self._industry_cache.get(name)

    def initiate_resources(self, search_results) -> List[Vacancy]:
        vacancies = []
        for result in search_results:
            vacancy = self._initiate_vacancy(result)
            if vacancy is not None:
                vacancies.append(vacancy)
        return vacancies

    def initiate_resource(self, enriched_result):
        return self._initiate_vacancy(enriched_result)

    def _initiate_vacancy(self, result):
        vacancy_portal_id = result.get('id')
        if vacancy_portal_id is None:
            logger.warning(
                f"Skipping result with missing id: "
                f"{result.get('positionTitle', 'Unknown')}"
            )
            return None
        return self._build_vacancy(result, vacancy_portal_id)

    def _build_vacancy(self, result, vacancy_portal_id):
        url = self.config['vacancy_base_url'] +\
            self.config['vacancy_base_href'] + str(vacancy_portal_id)

        # Parse datetime fields
        first_seen = None
        if result.get('publishDate'):
            first_seen = parse_datetime(result.get('publishDate'))

        application_deadline = None
        if result.get('expirationDate'):
            application_deadline = parse_datetime(
                result.get('expirationDate')
            )

        # Create unsaved Vacancy instance with metadata
        vacancy = Vacancy(
            vacancy_portal_id=vacancy_portal_id,
            job_portal_id=int(self.portal_id),
            title=result.get('positionTitle'),
            company_name=result.get('employerName'),
            salary_from=result.get('salaryFrom'),
            salary_to=result.get('salaryTo'),
            url=url,
            first_seen=first_seen,
            last_seen=timezone.now(),
            application_deadline=application_deadline,
            state="CREATED",
        )

        # Employer identity — the search payload's employerId is the
        # stable join key to a Company (see
        # docs/company_linking_plan.md). Free on every portal.
        try:
            employer_id = int(result.get('employerId'))
        except (TypeError, ValueError):
            employer_id = None

        # Detail-page enrichment (nextjs portal): flatten the
        # standardDetails sections and OCR the attached file when
        # present, so image-only ads still feed keyword matching.
        detail = result.get('_detail')
        if detail:
            vacancy.detail_fetched_at = timezone.now()
            vacancy._pending_employer_detail = (
                company_linking.employer_detail_slice(detail)
            )
            if employer_id is None:
                employer_id = (
                    vacancy._pending_employer_detail['employer_id']
                )
            details = detail.get('details') or {}
            extra = self._standard_details_text(
                details.get('standardDetails')
            )
            file_id = (
                details.get('fileDetails') or {}
            ).get('fileId')
            if file_id:
                ocr_text, pending_file = (
                    self._ocr_vacancy_file(file_id)
                )
                if ocr_text:
                    extra = (extra + ' ' + ocr_text).strip()
                if pending_file is not None:
                    vacancy._pending_file = pending_file
            if extra:
                result['_extra_content'] = extra

        if employer_id is not None:
            vacancy._pending_employer = (
                employer_id, result.get('employerName')
            )

        # Store M2M data for later (after save)
        vacancy._pending_industries = []
        vacancy._pending_keywords = []

        # Collect industries — numeric portal categories are mapped
        # through the config's industry_mapping (e.g. "10" → "it"),
        # unmapped ids keep their numeric name lookup.
        industry_mapping = self.config.get('industry_mapping') or {}
        portal_industries = result.get('categories')
        if portal_industries:
            for portal_industry in portal_industries:
                industry_name = industry_mapping.get(
                    str(portal_industry), str(portal_industry)
                )
                industry = self._industry_named(industry_name)
                if industry:
                    vacancy._pending_industries.append(industry)

        # Collect keywords from portal's explicit keyword list
        keyword_by_name = {k.name: k for k in self.keywords_list}
        portal_keywords = result.get('keywords')
        if portal_keywords:
            for portal_keyword in portal_keywords:
                keyword = keyword_by_name.get(portal_keyword)
                if keyword:
                    vacancy._pending_keywords.append(keyword)

        # Collect keywords by searching within content
        searchable_content = (
            self._extract_searchable_content(result)
        )
        content_keywords = (
            self._find_keywords_in_content(searchable_content)
        )
        vacancy._pending_keywords.extend(content_keywords)

        logger.debug(
            f"Vacancy {vacancy_portal_id}: "
            f"Portal keywords: {len(portal_keywords or [])}, "
            f"Content keywords: {len(content_keywords)}"
        )
        return vacancy

    def create_or_update_resources(self, vacancies: List[Vacancy]):
        vacancies = [v for v in vacancies if v is not None]
        if self.enrich_search_results:
            logger.info(
                f"Detail enrichment totals: "
                f"{self._detail_fetches} fetched "
                f"({self._detail_with_about} with employer "
                f"'about'), {self._detail_skipped_fresh} "
                f"fresh-skipped, {self._detail_failed} failed"
            )
        scraped_ids = {v.vacancy_portal_id for v in vacancies}
        # Materialize once — a keyed dict beats a per-row .get().
        existing_by_portal_id = {
            v.vacancy_portal_id: v
            for v in Vacancy.objects.filter(
                vacancy_portal_id__in=scraped_ids
            )
        }

        new_vacancies = []
        changed_vacancies = []
        sighted = []
        m2m_vacancies = []

        for vacancy in vacancies:
            existing = existing_by_portal_id.get(
                vacancy.vacancy_portal_id
            )
            if existing is None:
                new_vacancies.append(vacancy)
                continue
            # Update existing vacancy. Most sightings only bump
            # last_seen — those go into one bulk UPDATE; rows that
            # actually change (filled-in fields, a fresh detail
            # fetch) get a real save via bulk_update.
            changed = False
            if vacancy.detail_fetched_at:
                existing.detail_fetched_at = (
                    vacancy.detail_fetched_at
                )
                changed = True
            if not existing.title and vacancy.title:
                existing.title = vacancy.title
                changed = True
            if not existing.company_name and vacancy.company_name:
                existing.company_name = vacancy.company_name
                changed = True
            if changed:
                existing.last_seen = timezone.now()
                changed_vacancies.append(existing)
            else:
                sighted.append(existing)
            # Transfer pending M2M data to existing instance
            existing._pending_industries = (
                vacancy._pending_industries
            )
            existing._pending_keywords = vacancy._pending_keywords
            existing._pending_file = getattr(
                vacancy, '_pending_file', None
            )
            existing._pending_employer = getattr(
                vacancy, '_pending_employer', None
            )
            existing._pending_employer_detail = getattr(
                vacancy, '_pending_employer_detail', None
            )
            m2m_vacancies.append(existing)

        if self.dry_run:
            employer_ids = {
                v._pending_employer[0]
                for v in (*new_vacancies, *m2m_vacancies, *sighted)
                if getattr(v, '_pending_employer', None)
            }
            logger.info(
                f"[dry-run] Would create {len(new_vacancies)} "
                f"new vacancies and update "
                f"{len(m2m_vacancies)} existing; "
                f"{len(employer_ids)} distinct employer(s) observed "
                f"— no vacancy/file/company writes."
            )
            return

        # Resolve companies before the INSERT so new rows carry the
        # FK; also assigns .company on existing/sighted rows.
        self._persist_companies(
            new_vacancies, changed_vacancies, sighted
        )

        if new_vacancies:
            Vacancy.objects.bulk_create(new_vacancies)
            logger.info(
                f"Created {len(new_vacancies)} new vacancies. \n\n"
            )

        if sighted:
            Vacancy.objects.filter(
                pk__in=[v.pk for v in sighted]
            ).update(last_seen=timezone.now())
        if changed_vacancies:
            Vacancy.objects.bulk_update(
                changed_vacancies,
                [
                    'last_seen', 'detail_fetched_at',
                    'title', 'company_name', 'company',
                ],
            )
        if m2m_vacancies:
            logger.info(
                f"Updated {len(m2m_vacancies)} "
                f"existing vacancies."
            )

        # M2M writes: collect every (vacancy, tag) pair across the
        # batch and insert the through rows in one bulk INSERT per
        # relation — unique_together makes conflicts harmless.
        industry_rows = []
        keyword_rows = []
        for vacancy in (*new_vacancies, *m2m_vacancies):
            for industry in vacancy._pending_industries:
                industry_rows.append(VacancyIndustries(
                    vacancy=vacancy, industry=industry,
                ))
            for keyword in vacancy._pending_keywords:
                keyword_rows.append(VacancyContainsKeyword(
                    vacancy=vacancy, keyword=keyword,
                ))
        if industry_rows:
            VacancyIndustries.objects.bulk_create(
                industry_rows, ignore_conflicts=True
            )
        if keyword_rows:
            VacancyContainsKeyword.objects.bulk_create(
                keyword_rows, ignore_conflicts=True
            )

        # Persist OCR'd vacancy files (file_id is unique — a file
        # already recorded for another run is left untouched)
        for vacancy in (*new_vacancies, *m2m_vacancies):
            vacancy_file = getattr(vacancy, '_pending_file', None)
            if vacancy_file is None:
                continue
            VacancyFile.objects.get_or_create(
                file_id=vacancy_file.file_id,
                defaults={
                    'vacancy': vacancy,
                    'content_type': vacancy_file.content_type,
                    'sha256': vacancy_file.sha256,
                    'extracted_text': vacancy_file.extracted_text,
                    'ai_model': vacancy_file.ai_model,
                    'ai_request': vacancy_file.ai_request,
                },
            )

        return

    def _persist_companies(
        self, new_vacancies, changed_vacancies, sighted
    ):
        """Resolve ``_pending_employer`` observations to Companies.

        Batched: one query for existing identities, bulk_create for
        the missing companies/identities, one bump UPDATE each, and
        one bulk INSERT + one UPDATE for 'name' alias sightings.
        Rich employer fields (``_pending_employer_detail``, nextjs
        detail pages only) go through
        ``company_linking.apply_employer_detail`` which carries the
        §4.1 reg-code conflict rules.

        Assigns ``vacancy.company`` in place — new rows are set
        before ``bulk_create``, changed rows ride the existing
        ``bulk_update``, and sighting-only rows get one grouped
        UPDATE per company when their FK is null or stale (e.g.
        after an admin merge).
        """
        now = timezone.now()
        vacancies = [*new_vacancies, *changed_vacancies, *sighted]
        employers = {}  # employer_id -> observed employerName
        details = {}    # employer_id -> employer_detail_slice
        for vacancy in vacancies:
            pending = getattr(vacancy, '_pending_employer', None)
            if pending:
                employers[pending[0]] = pending[1]
            detail = getattr(
                vacancy, '_pending_employer_detail', None
            )
            if detail and detail.get('employer_id') is not None:
                details[detail['employer_id']] = detail
        if not employers:
            return

        identities = {
            i.employer_id: i
            for i in CompanyIdentity.objects.filter(
                source=company_linking.SOURCE_CVLV,
                employer_id__in=employers,
            ).select_related('company')
        }
        new_companies = []
        new_identities = []
        for employer_id, name in employers.items():
            if employer_id in identities:
                continue
            company = Company(
                name=(name or '').strip(),
                first_seen=now, last_seen=now,
            )
            new_companies.append(company)
            new_identities.append(CompanyIdentity(
                company=company,
                source=company_linking.SOURCE_CVLV,
                employer_id=employer_id,
                first_seen=now, last_seen=now,
            ))
            identities[employer_id] = new_identities[-1]
        if new_companies:
            Company.objects.bulk_create(new_companies)
            CompanyIdentity.objects.bulk_create(new_identities)
            logger.info(
                f"Created {len(new_companies)} new companies."
            )

        # employer_id -> canonical Company (follow merged_into so
        # admin merges repoint future sightings automatically)
        companies = {}
        for employer_id, identity in identities.items():
            company = identity.company
            if company.merged_into_id is not None:
                company = company.canonical()
            companies[employer_id] = company

        # Rich employer fields — nextjs detail slices only; carries
        # the reg-code collision/change flagging.
        detailed_pks = set()
        about_pks = set()
        for employer_id, detail in details.items():
            company = companies.get(employer_id)
            if company is None:
                continue
            company_linking.apply_employer_detail(
                company, detail, now=now
            )
            detailed_pks.add(company.pk)
            if company.about:
                about_pks.add(company.pk)
        if details:
            logger.info(
                f"Employer detail applied to "
                f"{len(detailed_pks)} companies "
                f"({len(about_pks)} with 'about' text; "
                f"{len(details) - len(detailed_pks)} slices "
                f"without a matching company)"
            )

        # Renames among non-enriched employers — routine: the alias
        # sighting below records the name, just refresh the display
        # name (no review flag).
        renamed = {}
        for employer_id, name in employers.items():
            company = companies[employer_id]
            if company.pk in detailed_pks:
                continue
            name = (name or '').strip()
            if name and company.name != name:
                company.name = name
                renamed[company.pk] = company
        if renamed:
            Company.objects.bulk_update(
                list(renamed.values()), ['name']
            )

        # Observation windows.
        CompanyIdentity.objects.filter(
            source=company_linking.SOURCE_CVLV,
            employer_id__in=employers,
        ).update(last_seen=now)
        Company.objects.filter(
            pk__in={c.pk for c in companies.values()}
        ).update(last_seen=now)

        # 'name' alias sightings — bulk INSERT the new ones, one
        # grouped UPDATE bumps last_seen on pre-existing rows.
        observed = {
            (companies[eid].pk, (name or '').strip())
            for eid, name in employers.items() if name
        }
        if observed:
            existing = set(
                CompanyAlias.objects.filter(
                    company_id__in={c for c, _ in observed},
                    kind=CompanyAlias.KIND_NAME,
                    value__in={n for _, n in observed},
                ).values_list('company_id', 'value')
            )
            CompanyAlias.objects.bulk_create([
                CompanyAlias(
                    company_id=cid,
                    kind=CompanyAlias.KIND_NAME,
                    value=name,
                    first_seen=now, last_seen=now,
                )
                for cid, name in observed - existing
            ])
            to_bump = observed & existing
            if to_bump:
                q = Q()
                for cid, name in to_bump:
                    q |= Q(company_id=cid, value=name)
                CompanyAlias.objects.filter(
                    q, kind=CompanyAlias.KIND_NAME
                ).update(last_seen=now)

        # Sighting-only rows that lack a company (or still point at
        # a pre-merge one) — one UPDATE per distinct company. Done
        # before assigning .company below so the FK diff is visible.
        pks_by_company = {}
        for vacancy in sighted:
            pending = getattr(vacancy, '_pending_employer', None)
            if pending is None:
                continue
            company = companies.get(pending[0])
            if company is None:
                continue
            if vacancy.company_id != company.pk:
                pks_by_company.setdefault(
                    company.pk, []
                ).append(vacancy.pk)
        for company_id, pks in pks_by_company.items():
            Vacancy.objects.filter(pk__in=pks).update(
                company_id=company_id
            )

        for vacancy in vacancies:
            pending = getattr(vacancy, '_pending_employer', None)
            if pending is not None:
                company = companies.get(pending[0])
                if company is not None:
                    vacancy.company = company

import hashlib
import logging
import json
import os
import re
from django.conf import settings
from bs4 import BeautifulSoup
import urllib3
from .ai_jobs import VACANCY_IMAGE_OCR
from .models import Keyword, Vacancy, VacancyFile, Industry
from typing import List
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
        # Set enrich_search_results based on portal type
        self.enrich_search_results = self.config.get('type') != 'api'
        self.validate_result = False
        self.excluded_resources = []
        self._ai_client = None
        self._ocr_unavailable = False
        self._ocr_template = None
        self._detail_fetched_map = None
        self._search_total = None

    def load_config(self, portal_id):
        return load_portals_config().get(str(portal_id))

    def get_search_urls(self):
        if self.config.get('type') == 'nextjs':
            yield from self._nextjs_search_urls()
            return
        yield from self._keyword_search_urls()

    def _keyword_search_urls(self):
        """API portals: one search URL (and one checkpoint item)
        per keyword."""
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

    def _nextjs_search_urls(self):
        """Next.js portals: the whole offset-paginated sweep is
        one checkpoint item."""
        if self.runner is None:
            yield from self._get_nextjs_search_urls()
            return
        base_url = self.config['base_url'] + self.config['search_href']
        items = self.runner.sync_items(
            [('search', base_url, 0, None)]
        )
        for item in self.runner.pending_items(items):
            try:
                for url in self._get_nextjs_search_urls():
                    yield url
                    self.runner.touch()
            except Exception as e:
                self.runner.item_failed(item, e)
                continue
            self.runner.item_done(item)

    def _get_nextjs_search_urls(self):
        """Public portal search pages (server-rendered Next.js).

        Offset-paginates ``search_params`` (e.g. an IT-category
        sweep) until a page comes back empty or ``total`` from the
        embedded JSON has been covered.
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
        if 'application/json' in content_type:
            data = json.loads(search_response.data.decode('utf-8'))
            vacancies = data.get('vacancies', [])
            return vacancies
        else:
            soup = BeautifulSoup(search_response.data, 'html.parser')
            vacancy_soup = soup.find_all('div', class_="show-expander-content")
            return vacancy_soup

    def remove_redundant_results(
      self,
      resources: List[Vacancy]
    ) -> List[Vacancy]:
        # Remove already processed vacancy id's in this session
        return resources

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
        if self.config.get('type') != 'nextjs':
            return super().enrich_result(result)
        if not self._needs_detail_fetch(result):
            return result
        info_link = self.get_resource_info_link(result)
        response = self.make_request(info_link)
        if response is None:
            logger.warning(
                f"Detail page fetch failed for vacancy "
                f"{result.get('id')}"
            )
            return result
        data = self._extract_next_data(response.data)
        detail = None
        if data:
            vacancies = (
                data.get('props', {})
                .get('pageProps', {})
                .get('vacancy') or {}
            )
            detail = vacancies.get(str(result['id']))
        if detail is None:
            logger.warning(
                f"No detail JSON for vacancy {result.get('id')} "
                f"at {info_link}"
            )
            return result
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

        # Detail-page enrichment (nextjs portal): flatten the
        # standardDetails sections and OCR the attached file when
        # present, so image-only ads still feed keyword matching.
        detail = result.get('_detail')
        if detail is not None:
            vacancy.detail_fetched_at = timezone.now()
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

        # Store M2M data for later (after save)
        vacancy._pending_industries = []
        vacancy._pending_keywords = []

        # Collect industries
        portal_industries = result.get('categories')
        if portal_industries:
            for portal_industry in portal_industries:
                industry = self.industries.filter(
                    name=portal_industry
                ).first()
                if industry:
                    vacancy._pending_industries.append(industry)

        # Collect keywords from portal's explicit keyword list
        portal_keywords = result.get('keywords')
        if portal_keywords:
            for portal_keyword in portal_keywords:
                keyword = (
                    self.keywords.filter(
                        name=portal_keyword
                    ).first()
                )
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
        scraped_ids = {v.vacancy_portal_id for v in vacancies}
        existing_vacancies = Vacancy.objects.filter(
            vacancy_portal_id__in=scraped_ids
        )
        existing_ids = set(
            existing_vacancies.values_list('vacancy_portal_id', flat=True)
        )

        new_vacancies = []
        vacancies_to_update_m2m = []

        for vacancy in vacancies:
            if vacancy.vacancy_portal_id in existing_ids:
                # Update existing vacancy
                existing = existing_vacancies.get(
                    vacancy_portal_id=vacancy.vacancy_portal_id
                )
                existing.last_seen = timezone.now()
                if vacancy.detail_fetched_at:
                    existing.detail_fetched_at = (
                        vacancy.detail_fetched_at
                    )
                if not existing.title and vacancy.title:
                    existing.title = vacancy.title
                if not existing.company_name and vacancy.company_name:
                    existing.company_name = vacancy.company_name
                if not self.dry_run:
                    existing.save()
                # Transfer pending M2M data to existing instance
                existing._pending_industries = (
                    vacancy._pending_industries
                )
                existing._pending_keywords = vacancy._pending_keywords
                existing._pending_file = getattr(
                    vacancy, '_pending_file', None
                )
                vacancies_to_update_m2m.append(existing)
            else:
                new_vacancies.append(vacancy)

        if self.dry_run:
            logger.info(
                f"[dry-run] Would create {len(new_vacancies)} "
                f"new vacancies and update "
                f"{len(vacancies_to_update_m2m)} existing "
                f"— no vacancy/file writes."
            )
            return

        if new_vacancies:
            Vacancy.objects.bulk_create(new_vacancies)
            logger.info(
                f"Created {len(new_vacancies)} new vacancies. \n\n"
            )
            # Add M2M relationships for new vacancies
            for vacancy in new_vacancies:
                for industry in vacancy._pending_industries:
                    vacancy.industries.add(industry)
                for keyword in vacancy._pending_keywords:
                    vacancy.keywords.add(keyword)

        if vacancies_to_update_m2m:
            logger.info(
                f"Updated {len(vacancies_to_update_m2m)} "
                f"existing vacancies."
            )
            # Update M2M relationships for existing vacancies
            for vacancy in vacancies_to_update_m2m:
                for industry in vacancy._pending_industries:
                    vacancy.industries.add(industry)
                for keyword in vacancy._pending_keywords:
                    vacancy.keywords.add(keyword)

        # Persist OCR'd vacancy files (file_id is unique — a file
        # already recorded for another run is left untouched)
        for vacancy in (*new_vacancies, *vacancies_to_update_m2m):
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

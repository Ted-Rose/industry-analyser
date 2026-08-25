import logging
import json
import os
import re
from django.conf import settings
from bs4 import BeautifulSoup
import urllib3
from .models import Keyword, Vacancy, Industry
from typing import List
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core_scraper.base import BaseScraper

logger = logging.getLogger('fetcher')


class VacancyScrapper(BaseScraper):
    def __init__(self, portal_id=1):
        super().__init__()
        self.config = self.load_config(portal_id)
        self.keywords = Keyword.objects
        self.industries = Industry.objects
        # Cache keywords list for content matching optimization
        self.keywords_list = list(self.keywords.all())
        # Set enrich_search_results based on portal type
        self.enrich_search_results = self.config.get('type') != 'api'

    def load_config(self, portal_id):
        portals_json = os.environ.get('FETCHER_PORTALS_JSON')
        if portals_json:
            portals = json.loads(portals_json)
            return portals.get(str(portal_id))
        config_path = os.path.join(settings.BASE_DIR, 'fetcher/config_v2.json')
        with open(config_path, 'r') as file:
            config = json.load(file)
            return config['portals'].get(str(portal_id))

    def get_search_urls(self):
        keywords = self.keywords.filter(only_filter=False).values('name')
        keywords = [keyword['name'] for keyword in keywords]

        base_url = self.config['base_url'] + self.config['search_href']
        for keyword in keywords:
            url = base_url + f"?limit=1000&keywords[]={keyword}"
            yield url
        return

    def parse_results(
        self,
        search_response: urllib3.response.HTTPResponse
    ) -> List:
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
            vacancy_portal_id = result.get('id')
            if vacancy_portal_id is None:
                logger.warning(
                    f"Skipping result with missing id: "
                    f"{result.get('positionTitle', 'Unknown')}"
                )
                continue

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

            vacancies.append(vacancy)
        return vacancies

    def create_or_update_resources(self, vacancies: List[Vacancy]):
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
                if not existing.title and vacancy.title:
                    existing.title = vacancy.title
                if not existing.company_name and vacancy.company_name:
                    existing.company_name = vacancy.company_name
                existing.save()
                # Transfer pending M2M data to existing instance
                existing._pending_industries = (
                    vacancy._pending_industries
                )
                existing._pending_keywords = vacancy._pending_keywords
                vacancies_to_update_m2m.append(existing)
            else:
                new_vacancies.append(vacancy)

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

        return

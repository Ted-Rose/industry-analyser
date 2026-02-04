import logging
import json
import os
from django.conf import settings
from bs4 import BeautifulSoup
import urllib3
from .models import Keyword, Vacancy, Industry
from typing import List
from django.utils import timezone

from core_scraper.base import BaseScraper

logger = logging.getLogger('fetcher')


class VacancyScrapper(BaseScraper):
    def __init__(self, portal_id=1):
        super().__init__()
        self.config = self.load_config(portal_id)
        self.keywords = Keyword.objects
        self.industries = Industry.objects

    def load_config(self, portal_id):
        config_path = os.path.join(settings.BASE_DIR, 'fetcher/config_v2.json')
        with open(config_path, 'r') as file:
            config = json.load(file)
            return config['portals'].get(str(portal_id))

    def get_search_urls(self):
        keywords = self.keywords.filter(only_filter=False).values('name')
        keywords = [keyword['name'] for keyword in keywords]

        base_url = self.config['base_url'] + self.config['search_href']
        for keyword in keywords:
            url = base_url + f"?limit=1000&keywords%5B0%5D={keyword}"
            yield url
        return

    def parse_results(
        self,
        search_response: urllib3.response.HTTPResponse
  ) -> List:
        if search_response.headers['Content-Type'] == 'application/json':
            self.enrich_search_results = False

            data = json.loads(search_response.data.decode('utf-8'))
            vacancies = data.get('vacancies', [])
            return vacancies
        else:
            self.enrich_search_results = True

            soup = BeautifulSoup(search_response.data, 'html.parser')
            vacancy_soup = soup.find_all('div', class_="show-expander-content")
            return vacancy_soup

    def remove_redundant_results(
      self,
      resources: List[Vacancy]
    ) -> List[Vacancy]:
        # Remove already processed vacancy id's in this session
        return resources

    def initiate_resources(self, search_results) -> List[Vacancy]:
        vacancies = []
        for result in search_results:
            vacancy_portal_id = result.get('id')
            if vacancy_portal_id is None:
                logger.warning(f"Skipping result with missing id: {result.get('positionTitle', 'Unknown')}")
                continue

            url = self.config['vacancy_base_url'] +\
                self.config['vacancy_base_href'] + str(vacancy_portal_id)

            vacancy, created = Vacancy.objects.get_or_create(
                vacancy_portal_id=vacancy_portal_id,
                defaults={
                    'title': result.get('positionTitle'),
                    'company_name': result.get('employerName'),
                    'salary_from': result.get('salaryFrom'),
                    'salary_to': result.get('salaryTo'),
                    'url': url,
                    'first_seen': result.get('publishDate'),
                    'last_seen': timezone.now(),
                    'application_deadline': result.get('expirationDate'),
                    'state': "CREATED",
                }
            )

            if not created:
                vacancy.last_seen = timezone.now()
                vacancy.save(update_fields=['last_seen'])

            # Handle dependencies (e.g., industries)
            portal_industries = result.get('categories')
            if portal_industries:
                for portal_industry in portal_industries:
                    industry = self.industries.filter(name=portal_industry).first()
                    if industry:
                        vacancy.industries.add(industry)

            # Handle dependencies (e.g., keywords)
            portal_keywords = result.get('keywords')
            if portal_keywords:
                for portal_keyword in portal_keywords:
                    keyword = self.keywords.filter(name=portal_keyword).first()
                    if keyword:
                        vacancy.keywords.add(keyword)

            vacancies.append(vacancy)
        return vacancies

    def create_or_update_resources(self, vacancies: List[Vacancy]):
        scraped_ids = {v.vacancy_portal_id for v in vacancies}
        existing_ids = set(
            Vacancy.objects.filter(
                vacancy_portal_id__in=scraped_ids
            ).values_list('vacancy_portal_id', flat=True)
        )

        new_vacancies = []
        ids_to_update = []

        for vacancy in vacancies:
            if vacancy.vacancy_portal_id in existing_ids:
                ids_to_update.append(vacancy.vacancy_portal_id)
            else:
                new_vacancies.append(vacancy)

        if ids_to_update:
            updated_count = Vacancy.objects.filter(vacancy_portal_id__in=ids_to_update).update(last_seen=timezone.now())
            logger.info(f"Updated {updated_count} existing vacancies.")

        if new_vacancies:
            Vacancy.objects.bulk_create(new_vacancies)
            logger.info(f"Created {len(new_vacancies)} new vacancies. \n\n")

        return

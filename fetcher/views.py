from django.shortcuts import render
import requests
from bs4 import BeautifulSoup
from .models import Vacancy, Company
import uuid

def fetcher(request):
  keywords_list = ['CEO', 'CFO', 'CTO']
  portal_search_base_urls = ['www.bigsite.com', 'www.longsite.com']
  
  for keywords in keywords_list:
    for search_url in portal_search_base_urls:
      search_response = requests.get(search_url, params={'keywords[0]': keywords})
      vacancy_urls = BeautifulSoup(search_response.content, 'html.parser').find_all('a')

      for vacancy_url in vacancy_urls:
        vacancy = requests.get(vacancy_url)
        vacancy_content = vacancy.content.decode("utf-8")

        # Store company in db
        company = Company.update_or_create(
            uuid = uuid.uuid4(),
            name = vacancy_content.company,
        )

        vacancy_contains_keywords = []
        for searchable_keywords in keywords_list:
          if searchable_keywords in vacancy_content:
            vacancy_contains_keywords.add(searchable_keywords)

        # Store vacancy in db
        Vacancy.update_or_create(
            uuid = uuid.uuid4(),
            company = company
            title = vacancy_content.title,
            url = vacancy_url,
            application_deadline = vacancy_content.deadline,
            state  ="fetched", # State might be "error" or "fetched"
            vacancy_found_by_keywords = keywords,
            vacancy_contains_keywords = vacancy_contains_keywords,
        )

  return render(request, 'fetcher/home.html')
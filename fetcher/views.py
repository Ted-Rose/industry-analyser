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
      search_response = requests.get(search_url)
      vacancy_urls = BeautifulSoup(search_response.content, 'html.parser').find_all('a')

      for vacancy_url in vacancy_urls:
        vacancy = requests.get(vacancy_url)
        vacancy_content = vacancy.content.decode("utf-8")

        Company.objects.create(
            uuid=uuid.uuid4(),
            name=vacancy_content.company,
        )

        # Store vacancy in db
        Vacancy.objects.create(
            uuid=uuid.uuid4(),
            title=vacancy_content.title,
            url=vacancy_url,
            state="fetched", # State might be "error" or "fetched"
            keywords=keywords,
        )

  return render(request, 'fetcher/home.html')
from django.shortcuts import render
from http.client import IncompleteRead
import requests
from bs4 import BeautifulSoup
from .models import Vacancy
import uuid
import os
import json
from django.conf import settings
import time
from datetime import datetime


def fetcher(request):
 # Path to your JSON config file
  config_path = os.path.join(settings.BASE_DIR, 'fetcher/config.json')

  with open(config_path, 'r') as file:
      config = json.load(file)  # Load JSON data into a Python dictionary

  # Access the required keys from the dictionary
  keywords_list = config['keywords_list']
  portals = config['portals']
  print("portals", portals)
  # keywords_list = config['keywords_list']
  # portal_search_base_urls = config['portal_search_base_urls']
  
  for keywords in keywords_list:
    for _, portal in portals.items():
      print("portal:", portal)
      print("portal:", portal['base_url'])
      print("portal:", portal['search_href'])
      search_url = portal['base_url'] + portal['search_href']
      #TODO handle error responses with a retry for few times
      search_response = requests.get(search_url, params={
        portal['keywords_param']: keywords,
        portal['limit_param']:1000,
      })
      links = BeautifulSoup(search_response.content, 'html.parser').find_all('a')

      for link in links:
        href = link.get('href')
        if not href or not href.startswith(portal["vacancy_base_href"]):
          # Not all hrefs link to vacancies, some link to company logos, etc
          continue
        
        title = link.text.strip()

        print("title:", title)
        url = portal['base_url'] + href
        if Vacancy.objects.filter(url=url).exists():
            print("Skipping - href already exists in the Vacancies table.")
            continue

        try:
            vacancy = requests.get(url)
        except IncompleteRead as e:
            print("IncompleteRead: ", e)
            print("Retrying in 5s...")
            time.sleep(5)
            vacancy = requests.get(url)

        vacancy_content = vacancy.content.decode("utf-8")
        # print("vacancy_content:\n", vacancy_content)
        # if vacancy_content: 
      #   # Store company in db
      #   company = Company.update_or_create(
      #       uuid = uuid.uuid4(),
      #       name = vacancy_content.company,
      #   )

      #   vacancy_contains_keywords = []
      #   for searchable_keywords in keywords_list:
      #     if searchable_keywords in vacancy_content:
      #       vacancy_contains_keywords.add(searchable_keywords)

        # Store vacancy in db
        Vacancy.objects.create(
            id = uuid.uuid4(),
            url = url,
            first_seen=datetime.now(),        )
        return render(request, 'fetcher/home.html')
      
      # Fetch all vacancies from database with creation date today

      # For user in users table assing vacancies that match user desired keywords
      # Notify user about all vacancies if notification settings match the finding

  return render(request, 'fetcher/home.html')

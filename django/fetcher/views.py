from django.shortcuts import render
from http.client import IncompleteRead
import requests
import re
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
    print("\n\n\nSearching for keywords: ", keywords)
    for _, portal in portals.items():
      print("portal:", portal)
      # print("portal:", portal['base_url'])
      # print("portal:", portal['search_href'])
      job_portal_id = portal['id']
      search_url = portal['base_url'] + portal['search_href']
      #TODO handle error responses with a retry for few times
      search_response = requests.get(search_url, params={
        portal['keywords_param']: keywords,
        portal['limit_param']:1000,
      })
      links = None
      links = BeautifulSoup(search_response.content, 'html.parser').find_all('a')
      # print("links", links)

      # print("search_response", search_response.content)
      parsed_content = None

      try:
          parsed_content = json.loads(search_response.content)
      except json.JSONDecodeError:
          parsed_content = None
          print("The content is not valid JSON.")

      if parsed_content:
        for vacancy in parsed_content.get('vacancies'):
            position = vacancy.get('positionTitle')
            print("\n\nposition", position)
            vacancy_portal_id = vacancy.get('id')
            print("vacancy_portal_id", vacancy_portal_id)
            url = portal['vacancy_base_url'] + portal['vacancy_base_href'] + str(vacancy_portal_id)
            print("url", url)
            company_id = vacancy.get('employerName')
            print("company_id", company_id)
            print("job_portal_id", job_portal_id)
            salary_from = vacancy.get('salaryFrom')
            print("salary_from", salary_from)
            salary_to = vacancy.get('salaryTo')
            print("salary_to", salary_to)
            first_seen = vacancy.get('publishDate')
            print("first_seen", first_seen)
            last_seen = datetime.now()
            print("last_seen", last_seen)
            application_deadline = vacancy.get('expirationDate')
            print("application_deadline", application_deadline)
      else: 
        for link in links:
          href = link.get('href')
          if not href or not href.startswith(portal["vacancy_base_href"]):
            # Not all hrefs link to vacancies, some link to company logos, etc
            continue
          
          url = portal['base_url'] + href
          if Vacancy.objects.filter(url=url).exists():
              print("Skipping - href already exists in the Vacancies table.")
              continue

          try:
            headers = {
              'Accept': 'application/json',
            }

            # Send the GET request with the headers
            vacancy = requests.get(url, headers=headers)
          except IncompleteRead as e:
              print("IncompleteRead: ", e)
              print("Retrying in 5s...")
              time.sleep(5)
              vacancy = requests.get(url)

          vacancy_content = vacancy.content.decode("utf-8")
          title = link.text.strip()
          # print("title:", title)

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
              first_seen=datetime.now(),        
          )
          return render(request, 'fetcher/home.html')
        
  return render(request, 'fetcher/home.html')

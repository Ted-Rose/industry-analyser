import logging
from django.shortcuts import render, redirect
from http.client import IncompleteRead
import requests
from bs4 import BeautifulSoup
from .models import Keyword, Vacancy, VacancyContainsKeyword
import uuid
import os
import json
from django.conf import settings
import time
import random
from django.utils import timezone
from .forms import KeywordForm


logger = logging.getLogger(__name__)
today = timezone.now().date()

def save_or_update_keywords(vacancy_id, content, keywords_queryset):
    if not content:
        return
    vacancy = Vacancy.objects.filter(id=vacancy_id).first()

    for keyword in keywords_queryset:
        if keyword.name.lower() in content.lower():
            existing_entries = VacancyContainsKeyword.objects.filter(
                vacancy=vacancy,
                keyword=keyword
            )
            if existing_entries.exists():
                continue
            else:
                VacancyContainsKeyword.objects.create(
                    vacancy=vacancy,
                    keyword=keyword
                )


def fetcher(request):
    logger.info(f"Fetching initiated on {today}")
    config_path = os.path.join(settings.BASE_DIR, 'fetcher/config.json')

    with open(config_path, 'r') as file:
        config = json.load(file)
    keywords_queryset = Keyword.objects.filter(only_filter=False)
    keywords_list = [keyword.name for keyword in keywords_queryset]
    portals = config['portals']

    for keywords in keywords_list:

        keyword_obj = Keyword.objects.filter(name=keywords).first()
        if not keyword_obj:
            continue

        # newest_entry = VacancyContainsKeyword.objects.filter(
        #     keyword=keyword_obj
        # ).order_by('-vacancy__last_seen').first()

        # if newest_entry.vacancy.last_seen.date() <= today:
        #     logger.info(f"Keyword {keywords} already fetched today. Skipping.")
        #     continue

        # Don't overwhelm portals with a request burst
        time.sleep(random.uniform(5, 10))
        logger.info(f"Searching for keywords: {keywords}")
        for _, portal in portals.items():
            logger.info(f"Searching in portal: {portal['vacancy_base_url']}")
            search_url = portal['base_url'] + portal['search_href']
            try:
                search_response = requests.get(search_url, params={
                    portal['keywords_param']: keywords,
                    portal['limit_param']:1000,
                })
            except requests.exceptions.RequestException as e:
                logger.error(f"Error in fetching data: {e}. Retrying...")
                time.sleep(random.uniform(5, 10))
                search_response = requests.get(search_url, params={
                    portal['keywords_param']: keywords,
                    portal['limit_param']:1000,
                })
            links = None
            links = BeautifulSoup(search_response.content, 'html.parser').find_all('a')

            parsed_content = None

            try:
                parsed_content = json.loads(search_response.content)
            except json.JSONDecodeError:
                parsed_content = None
                print("The content is not valid JSON.")
                logger.warning("The content is not valid JSON.")

            if parsed_content:
                for vacancy in parsed_content.get('vacancies'):
                    vacancy_portal_id = vacancy.get('id')
                    url = portal['vacancy_base_url'] + portal['vacancy_base_href'] + str(vacancy_portal_id)
                    title = vacancy.get('positionTitle')

                    existing_vacancy = Vacancy.objects.filter(url=url).first()

                    if existing_vacancy:
                        existing_vacancy.last_seen = timezone.now()
                        existing_vacancy.title = title
                        existing_vacancy.salary_from = vacancy.get('salaryFrom')
                        existing_vacancy.salary_to = vacancy.get('salaryTo')
                        existing_vacancy.application_deadline = vacancy.get('expirationDate')
                        existing_vacancy.state = "UPDATED",
                        existing_vacancy.save()
                        logger.info(f"Updated title and url: {title, url}")
                        vacancy_id = existing_vacancy.id
                    else:
                        vacancy_id = uuid.uuid4()
                        Vacancy.objects.create(
                        id = vacancy_id,
                        company_name = vacancy.get('employerName'),
                        job_portal_id = portal['id'],
                        title = title,
                        industry = vacancy.get('categories'),
                        salary_from = vacancy.get('salaryFrom'),
                        salary_to = vacancy.get('salaryTo'),
                        url = url,
                        first_seen = vacancy.get('publishDate'),
                        last_seen = timezone.now(),
                        vacancy_portal_id = vacancy_portal_id,
                        application_deadline = vacancy.get('expirationDate'),
                        state = "CREATED",
                        )
                        logger.info(f"Saved title and url: {title, url}")
                    
                    
                    vacancy_content = vacancy.get('positionContent')
                    # Get keywords and ensure it's a list or an empty list if None
                    keywords = vacancy.get('keywords', [])
                    if not isinstance(keywords, list):
                        keywords = []

                    # Convert the list of keywords to a single string, separated by spaces
                    keywords_str = ' '.join(keywords) if keywords else ''
                    if vacancy_content:
                        vacancy_content = (title + vacancy_content + keywords_str).lower()
                    else:
                        vacancy_content = (title + keywords_str).lower()
                    # print("vacancy_content: ", vacancy_content)
                    save_or_update_keywords(vacancy_id, vacancy_content, keywords_queryset)
            else:
                for link in links:
                    href = link.get('href')
                    if not href or not href.startswith(portal["vacancy_base_href"]):
                        # Not all hrefs link to vacancies, some link to company logos, etc
                        continue

                    url = portal['base_url'] + href
                    if Vacancy.objects.filter(url=url).exists():
                        print("Skipping - href already exists in the Vacancies table.")
                        logger.info("Skipping - href already exists in the Vacancies table.")
                        continue

                    try:
                        vacancy = requests.get(url)
                    except requests.exceptions.RequestException as e:
                        print("Error in fetching data: ", e, "\n Retrying...")
                        logger.error(f"Error in fetching data: {e}. Retrying...")
                        time.sleep(random.uniform(5, 10))
                        vacancy = requests.get(url)

                    vacancy_content = vacancy.content.decode("utf-8").lower()
                    title = link.text.strip()

                    Vacancy.objects.create(
                        id = uuid.uuid4(),
                        url = url,
                        first_seen=timezone.now(),
                    )
                    print("Saved url: ", url)
                    logger.info(f"Saved url: {url}")
            return render(request, 'fetcher/home.html')

    return render(request, 'fetcher/home.html')


def find_vacancies(request):
    keywords = Keyword.objects.all()

    include_keywords = request.GET.getlist('include_keywords')
    exclude_keywords = request.GET.getlist('exclude_keywords')
    #TODO Don't fetch all vacancies
    vacancies = Vacancy.objects.all()

    if include_keywords:
        vacancies = vacancies.filter(
            vacancycontainskeyword__keyword__name__in=include_keywords
        ).distinct()

    if exclude_keywords:
        vacancies = vacancies.exclude(
            vacancycontainskeyword__keyword__name__in=exclude_keywords
        ).distinct()

    if not vacancies:
      vacancies = "Please select a keyword!"

    return render(request, 'fetcher/vacancies.html', {
        'vacancies': vacancies,
        'keywords': keywords
    })

def add_keyword(request):
    hardcoded_password = settings.HARD_CODED_PASSWORD
    if request.method == 'POST':
        name = request.POST.get('name')
        only_filter = request.POST.get('only_filter') == 'on'  # Checkbox value is 'on' if checked
        password = request.POST.get('password')

        if password != hardcoded_password:
            return render(request, 'add_keyword.html', {'error': 'Invalid password.'})

    if request.method == 'POST':
        form = KeywordForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('find_vacancies')
    else:
        form = KeywordForm()
    return render(request, 'fetcher/add_keyword.html', {'form': form})
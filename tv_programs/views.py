from django.shortcuts import render
from django.db.models import Q
import requests
from bs4 import BeautifulSoup

from .models import Program, Channel

import logging

logger = logging.getLogger(__name__)


def spoki_page_view(request):
    url = "https://spoki.lv/stilsmode/Kas-ar-mani-notika-Cilveki-atceras-savus/932253"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes
        soup = BeautifulSoup(response.content, 'html.parser')

        title = soup.find('h1', class_='article-title').get_text() if soup.find('h1', class_='article-title') else "Title not found"
        content_div = soup.find('div', class_='article-body-content')
        content = str(content_div) if content_div else "<p>Content not found.</p>"

    except requests.exceptions.RequestException as e:
        title = "Error"
        content = f"<p>Could not fetch content from URL: {e}</p>"

    context = {
        'title': title,
        'content': content,
    }
    return render(request, 'tv_programs/spoki_page.html', context)


def program_list(request):
    """
    View for listing TV programs with filtering options.
    """
    content_rating = request.GET.get('content_rating', None)
    rating_value = request.GET.get('rating_value', None)
    start_date = request.GET.get('start_date', None)
    end_date = request.GET.get('end_date', None)
    channel_id = request.GET.get('channel', None)
    exclude_channel_id = request.GET.get('exclude_channel', None)

    # Build query
    query = Q()

    if content_rating:
        query &= Q(content_rating=content_rating)
    if rating_value:
        query &= Q(rating_value__gte=float(rating_value))
    if start_date:
        query &= Q(start_time__date__gte=start_date)
    if end_date:
        query &= Q(start_time__date__lte=end_date)
    if channel_id:
        query &= Q(channel_id=channel_id)
    if exclude_channel_id:
        query &= ~Q(channel_id=exclude_channel_id)

    programs = Program.objects.filter(query).order_by('-start_time')

    channels = Channel.objects.all()

    context = {
        'programs': programs,
        'channels': channels,
        'filters': {
            'content_rating': content_rating,
            'rating_value': rating_value,
            'start_date': start_date,
            'end_date': end_date,
            'channel_id': channel_id,
            'exclude_channel_id': exclude_channel_id,
        }
    }

    return render(request, 'tv_programs/program_list.html', context)

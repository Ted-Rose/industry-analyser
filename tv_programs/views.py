from django.shortcuts import render
from django.db.models import Q
from datetime import date, timedelta

from .models import Program, Channel

import logging

logger = logging.getLogger(__name__)


def program_list(request):
    """
    View for listing TV programs with filtering options.
    """
    content_rating = request.GET.get('content_rating', None)
    # Default 'not_content_rating' to 'R' if not specified
    not_content_rating = request.GET.get('not_content_rating')
    if not_content_rating is None:
        not_content_rating = 'R'
    rating_value = request.GET.get('rating_value', None)
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    # Default dates to a 7-day window if not provided
    if not end_date_str:
        end_date = date.today()
    else:
        end_date = date.fromisoformat(end_date_str)

    if not start_date_str:
        start_date = end_date - timedelta(days=7)
    else:
        start_date = date.fromisoformat(start_date_str)

    channel_name = request.GET.get('channel', None)
    exclude_channel_name = request.GET.get('exclude_channel', None)

    # Build query
    query = Q()

    if content_rating:
        query &= Q(pg_rating=content_rating)
    if not_content_rating:
        query &= ~Q(pg_rating=not_content_rating)
    if rating_value:
        query &= Q(imdb_rating__gte=float(rating_value))

    # Always filter by date range
    query &= Q(start_time__date__gte=start_date)
    query &= Q(start_time__date__lte=end_date)
    if channel_name:
        query &= Q(channel__name=channel_name)
    if exclude_channel_name:
        query &= ~Q(channel__name=exclude_channel_name)

    programs = Program.objects.select_related('channel').filter(query).order_by('channel__name')

    channels = Channel.objects.all()

    context = {
        'programs': programs,
        'channels': channels,
        'filters': {
            'content_rating': content_rating,
            'not_content_rating': not_content_rating,
            'rating_value': rating_value,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'channel_name': channel_name,
            'exclude_channel_name': exclude_channel_name,
        }
    }

    return render(request, 'tv_programs/program_list.html', context)

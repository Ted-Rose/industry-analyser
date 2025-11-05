from django.shortcuts import render
from django.db.models import Q

from .models import Program, Channel

import logging

logger = logging.getLogger(__name__)


def program_list(request):
    """
    View for listing TV programs with filtering options.
    """
    content_rating = request.GET.get('content_rating', None)
    not_content_rating = request.GET.get('not_content_rating', None)
    rating_value = request.GET.get('rating_value', None)
    start_date = request.GET.get('start_date', None)
    end_date = request.GET.get('end_date', None)
    channel_id = request.GET.get('channel', None)
    exclude_channel_id = request.GET.get('exclude_channel', None)

    # Build query
    query = Q()

    if content_rating:
        query &= Q(pg_rating=content_rating)
    if not_content_rating:
        query &= ~Q(pg_rating=not_content_rating)
    if rating_value:
        query &= Q(imdb_rating__gte=float(rating_value))
    if start_date:
        query &= Q(start_time__date__gte=start_date)
    if end_date:
        query &= Q(start_time__date__lte=end_date)
    if channel_id:
        query &= Q(channel_id=channel_id)
    if exclude_channel_id:
        query &= ~Q(channel_id=exclude_channel_id)

    programs = Program.objects.select_related('channel').filter(query).order_by('-start_time')

    channels = Channel.objects.all()

    context = {
        'programs': programs,
        'channels': channels,
        'filters': {
            'content_rating': content_rating,
            'not_content_rating': not_content_rating,
            'rating_value': rating_value,
            'start_date': start_date,
            'end_date': end_date,
            'channel_id': channel_id,
            'exclude_channel_id': exclude_channel_id,
        }
    }

    return render(request, 'tv_programs/program_list.html', context)

from datetime import date, timedelta
import logging

import requests
from bs4 import BeautifulSoup
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Channel, Program, Show, ShowPreference

logger = logging.getLogger("tv_programs")


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


def _preference_qs(request):
    """ShowPreferences visible to this visitor: the anonymous owner's
    (user IS NULL) plus, for a logged-in user, their own."""
    qs = ShowPreference.objects.all()
    if request.user.is_authenticated:
        return qs.filter(Q(user__isnull=True) | Q(user=request.user))
    return qs.filter(user__isnull=True)


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
    show_disliked = request.GET.get('show_disliked') == '1'

    # Build query
    query = Q()

    if content_rating:
        query &= Q(show__pg_rating=content_rating)
    if not_content_rating:
        query &= (
            Q(show__isnull=True)
            | ~Q(show__pg_rating=not_content_rating)
        )
    if rating_value:
        try:
            query &= Q(show__imdb_rating__gte=float(rating_value))
        except (TypeError, ValueError):
            pass

    # Always filter by date range
    query &= Q(start_time__date__gte=start_date)
    query &= Q(start_time__date__lte=end_date)
    if channel_name:
        query &= Q(channel__name=channel_name)
    if exclude_channel_name:
        query &= ~Q(channel__name=exclude_channel_name)

    programs = Program.objects.select_related('show', 'channel').filter(
        query
    ).order_by('channel__name')

    preferences = list(
        _preference_qs(request).select_related('show')
    )
    reactions = {p.show_id: p.reaction for p in preferences}

    # Disliked shows (and every show sharing a disliked series_title)
    # are hidden unless ?show_disliked=1.
    if not show_disliked:
        disliked_ids = {
            p.show_id
            for p in preferences
            if p.reaction == ShowPreference.Reaction.DISLIKE
        }
        disliked_series = {
            p.show.series_title
            for p in preferences
            if p.reaction == ShowPreference.Reaction.DISLIKE
            and p.show.series_title
        }
        if disliked_ids:
            programs = programs.exclude(show_id__in=disliked_ids)
        if disliked_series:
            programs = programs.exclude(
                show__series_title__in=disliked_series
            )

    for program in programs:
        program.user_reaction = reactions.get(program.show_id)

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
            'show_disliked': show_disliked,
        }
    }

    return render(request, 'tv_programs/program_list.html', context)


@require_POST
def react_to_show(request, show_id, reaction):
    """Toggle a like/dislike on a Show. Posting the same reaction
    again removes it."""
    show = get_object_or_404(Show, pk=show_id)
    if reaction not in ShowPreference.Reaction.values:
        return HttpResponseBadRequest('unknown reaction')
    user = request.user if request.user.is_authenticated else None
    pref = ShowPreference.objects.filter(show=show, user=user).first()
    if pref is not None and pref.reaction == reaction:
        pref.delete()
    elif pref is not None:
        pref.reaction = reaction
        pref.save(update_fields=['reaction'])
    else:
        ShowPreference.objects.create(
            show=show, user=user, reaction=reaction
        )

    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}
    ):
        return redirect(next_url)
    return redirect('tv_programs:program_list')

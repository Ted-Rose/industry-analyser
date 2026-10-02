"""Helpers shared by the tv ninja router (tv_programs/api.py).

The program_list / spoki_page / react_to_show FBVs were retired in
the React cutover — /tv/* serves the SPA shell and GET/POST ops
live at /api/tv/*. `requests` is an existing dependency (spoki).
"""
import logging
import re

import requests
from bs4 import BeautifulSoup
from django.db.models import Q

from .models import ShowPreference

logger = logging.getLogger('tv_programs')

SPOKI_PAGE_URL = (
    'https://spoki.lv/ko-sodien-rada-televizija'
    '/24-08-2025-25-08-2025/1185808'
)


def _fetch_spoki_page():
    """Fetch the (hardcoded) spoki.lv article and return
    (title, content) where content is the article's HTML fragment.
    Returns a placeholder message on fetch/parse failure."""
    try:
        resp = requests.get(SPOKI_PAGE_URL, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning('spoki page fetch failed: %s', exc)
        return 'Spoki', 'Failed to load the page.'
    soup = BeautifulSoup(resp.text, 'html.parser')
    # .string is None on a multi-child/empty <title> — get_text() with
    # an '' fallback keeps the SpokiPageOut.title: str contract intact.
    title = (
        soup.title.get_text(strip=True) if soup.title else ''
    ) or 'Spoki'
    divs = soup.find_all(
        'div',
        class_=re.compile(r'show-memoir__text.*editor-text-content'),
    )
    content = ''.join(str(d) for d in divs)
    if not content:
        content = 'No content found'
    return title, content


def _preference_qs(request):
    """ShowPreference rows visible to this request — anonymous
    visitors see the shared user-NULL bucket; authenticated users
    see it merged with their own rows."""
    qs = ShowPreference.objects.all()
    if request.user.is_authenticated:
        return qs.filter(Q(user__isnull=True) | Q(user=request.user))
    return qs.filter(user__isnull=True)

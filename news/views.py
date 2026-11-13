"""news Django views — article_audio, the server-rendered digest
pages and the robot-facing surface (sitemap_xml, llms_txt).

The /news/ index and /news/<date>/ pages render the digest
inside #root of the shared SPA shell (news/digest_shell.html):
React replaces it on mount so human readers keep the full app,
while crawlers and agents that never run JavaScript (e.g.
Gemini's fetcher) read the rendered HTML at the same canonical
URLs. Every other page is the /news/ SPA backed by /api/news/
ops in news/api.py.
"""
import os
from datetime import datetime

from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.html import escape
from django.views.decorators.csrf import ensure_csrf_cookie

from industry_analyser.views import _spa_shell_context, edge_public_cache

from .models import NewsArticleAudio, NewsDigest
from .syndication import (
    DIGEST_WINDOW_DAYS,
    digest_day_url,
    digest_items_for,
    recent_digest_items,
)


def article_audio(request, pk):
    """Audio seam for a future TTS feature: serve a ready
    NewsArticleAudio's file_path when it exists on disk. No
    generator fills the table yet, so this 404s today — the
    URL contract is what matters."""
    audio = (
        NewsArticleAudio.objects
        .filter(article_id=pk, status='ready')
        .exclude(file_path='')
        # Several engines/voices may be ready — newest wins.
        .order_by('-created_at', '-pk')
        .first()
    )
    if audio is None or not os.path.isfile(audio.file_path):
        raise Http404('No ready audio for this article')
    return FileResponse(open(audio.file_path, 'rb'))


# --- Server-rendered digest pages ---

# feed_url/feed_title mirror the react_app_news partial in
# urls.py — every /news/ page advertises the RSS feed.
_FEED_KWARGS = {
    'feed_url': '/news/rss.xml',
    'feed_title': 'Industry Analyser — Latvian news digest',
}


def _digest_groups(items):
    """Items queryset -> [{'date', 'url', 'items'}] newest first,
    the context news/digest_shell.html renders."""
    by_day = {}
    for item in items:
        by_day.setdefault(item.digest.date, []).append(item)
    return [
        {'date': day, 'url': digest_day_url(day), 'items': group}
        for day, group in by_day.items()
    ]


def _news_shell_context(request, title='News'):
    return _spa_shell_context(
        request, 'news', title=title, **_FEED_KWARGS,
    )


@ensure_csrf_cookie
def digest_list_page(request):
    """GET /news/ — the last 7 days of digests server-rendered
    inside the SPA shell's #root (the same window the RSS feed
    and llms.txt expose)."""
    if request.method not in ('GET', 'HEAD'):
        raise Http404
    context = _news_shell_context(request)
    context['digest_groups'] = _digest_groups(
        recent_digest_items()
    )
    return render(request, 'news/digest_shell.html', context)


@ensure_csrf_cookie
def digest_detail_page(request, date):
    """GET /news/<date>/ — one digest day server-rendered at any
    age, so the sitemap's full history is readable HTML.

    Two audiences shape the contract: a string that parses as a
    date is a digest page — missing digests 404 rather than
    soft-404 an empty shell across infinite date space. Anything
    else ('audio', typos, retired client routes) is not our
    page at all — serve the plain shell and let React Router's
    '*' handle it, exactly as before the SSR cutover."""
    if request.method not in ('GET', 'HEAD'):
        raise Http404
    context = _news_shell_context(
        request, title=f'News {date}'
    )
    try:
        day = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        return render(request, 'spa_shell.html', context)
    digest = get_object_or_404(NewsDigest, date=day)
    context['digest_groups'] = _digest_groups(
        digest_items_for(digest)
    )
    return render(request, 'news/digest_shell.html', context)


@edge_public_cache
def sitemap_xml(request):
    """XML sitemap — the public pages a crawler should index:
    landing, the /news/ digest index and every digest day. The
    digest window is not capped here: a sitemap is an exhaustive
    URL inventory, not a freshness surface (one row per day —
    even years of digests stay far under the 50k URL limit)."""
    digests = list(NewsDigest.objects.order_by('-date'))
    newest = digests[0].date if digests else None
    paths = [
        ('/', newest),
        ('/news/', newest),
        ('/news/rss.xml', newest),
    ] + [
        (digest_day_url(digest.date), digest.date)
        for digest in digests
    ]
    urls = ''.join(
        '<url><loc>{loc}</loc>{lastmod}</url>'.format(
            loc=escape(request.build_absolute_uri(path)),
            lastmod=(
                f'<lastmod>{lastmod.isoformat()}</lastmod>'
                if lastmod else ''
            ),
        )
        for path, lastmod in paths
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset '
        'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'{urls}</urlset>\n'
    )
    return HttpResponse(xml, content_type='application/xml')


@edge_public_cache
def llms_txt(request):
    """llms.txt — markdown for LLM agents (the convention they
    are trained to fetch, like robots.txt for crawlers). Lists
    the last 7 days of digests: each day's page URL plus its
    ranked stories with the confirmed member article URLs."""
    lines = [
        '# Industry Analyser',
        '',
        '> Latvian web-portal scraping and analysis mini-apps. '
        'The news digest ranks the top stories each day across '
        'Latvian outlets (LSM, Delfi, TVNET, Diena, ...).',
        '',
        f'## News digest — last {DIGEST_WINDOW_DAYS} days',
        '',
    ]
    items_by_day = {}
    for item in recent_digest_items():
        items_by_day.setdefault(item.digest.date, []).append(item)
    if not items_by_day:
        lines.append('No digests published yet.')
    for day, day_items in items_by_day.items():
        digest_url = request.build_absolute_uri(
            digest_day_url(day)
        )
        lines.append(f'### [{day.isoformat()}]({digest_url})')
        lines.append('')
        for item in day_items:
            articles = getattr(
                item.story, 'confirmed_articles', [],
            )
            if articles:
                first = articles[0]
                # One outlet can carry several member articles —
                # dedupe names, preserving coverage order.
                others = dict.fromkeys(
                    a.source.name for a in articles[1:]
                )
                suffix = (
                    f" (+{', '.join(others)})" if others else ''
                )
                lines.append(
                    f'- [{item.headline}]({first.link})'
                    f' — {first.source.name}{suffix}'
                )
            else:
                lines.append(f'- {item.headline}')
        lines.append('')
    lines += [
        '## Machine-readable',
        '',
        '- [RSS feed (last 7 days)]'
        f"({request.build_absolute_uri('/news/rss.xml')})",
        '- [Digest JSON API]'
        f"({request.build_absolute_uri('/api/news/digests/')}"
        '?period=week)',
        '- [XML sitemap]'
        f"({request.build_absolute_uri('/sitemap.xml')})",
        '',
    ]
    return HttpResponse(
        '\n'.join(lines), content_type='text/plain; charset=utf-8'
    )

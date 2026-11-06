"""news Django views — article_audio plus the robot-facing
digest surface (sitemap_xml, llms_txt); every other page is the
/news/ SPA backed by /api/news/ ops in news/api.py.

The SPA shell serves no content to crawlers that don't run
JavaScript, so the digest's discovery surface is server-rendered
here: sitemap.xml indexes every digest day and llms.txt hands
LLM agents the last 7 days of digests with their URLs.
"""
import os

from django.http import FileResponse, Http404, HttpResponse
from django.utils.html import escape

from .models import NewsArticleAudio, NewsDigest
from .syndication import (
    DIGEST_WINDOW_DAYS,
    digest_day_url,
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

"""news URLconf — server-rendered digest pages + React SPA
shell + the article-audio binary view. Mounted at /news/ in
industry_analyser/urls.py.

The digest index ('') and day pages ('<str:date>/') are
server-rendered inside the SPA shell (news/digest_shell.html):
React replaces the #root markup on mount, while crawlers that
never run JavaScript read the digest HTML — the same canonical
URLs serve both audiences. Every other GET/HEAD path serves
the plain shell (Vite entry 'news') and React Router resolves
the page client-side. Route names stay so reverse() callers
keep working ('news:digest-detail' is reversed by the sitemap,
llms.txt and the RSS item links).

Retired: GET /news/audio/ and /news/story/<pk>/fragment/ —
the SPA calls /api/news/audio/ and /api/news/stories/<id>/
instead. Old GETs to those URLs fall through to the catch-all
shell (React Router sends them to /news/) and non-GETs get a
404 — the retired POST /news/ preferences/ form action can no
longer answer with HTML."""
from functools import partial

from django.urls import path

from industry_analyser.views import edge_public_cache, react_app_public
from . import views
from .syndication import NewsDigestFeed

app_name = 'news'

react_app_news = partial(
    react_app_public, entry='news', title='News',
    landing_desc='Daily digest of Latvian news across outlets.',
    feed_url='/news/rss.xml',
    feed_title='Industry Analyser — Latvian news digest',
)

urlpatterns = [
    # Server-rendered digest pages (see module docstring).
    path('', views.digest_list_page, name='digest-list'),
    # preferences/ MUST precede '<str:date>/' — 'str' would
    # swallow 'preferences' as a date (same subtlety the old
    # file documented for audio/ too; React Router ranks the
    # static /preferences route above /:date client-side, so
    # the client needs no extra care).
    path('preferences/', react_app_news, name='preferences'),
    # Outgoing RSS feed — the crawlable digest. MUST precede
    # '<str:date>/' the same way 'preferences/' does: 'str'
    # would swallow 'rss.xml' as a date.
    path('rss.xml', edge_public_cache(NewsDigestFeed()), name='rss'),
    # Binary FileResponse stays a Django view. Multi-segment —
    # '<str:date>/' can't collide; must precede <path:subpath>.
    path(
        'article/<int:pk>/audio/',
        views.article_audio,
        name='article-audio',
    ),
    path('<str:date>/', views.digest_detail_page,
         name='digest-detail'),
    # No trailing slash — matches 'x' and 'x/'; non-GET 404s.
    path('<path:subpath>', react_app_news, name='spa_subpath'),
]

"""news URLconf — React SPA shell + the article-audio binary
view. Mounted at /news/ in industry_analyser/urls.py.

Every GET/HEAD path under /news/ serves the shared SPA shell
(Vite entry 'news') and React Router resolves the page
client-side. The route names stay so reverse() callers keep
working ('news:digest-detail' is reversed in the story-card
API op; 'news:article-audio' serves the binary FileResponse).

Retired: GET /news/audio/ and /news/story/<pk>/fragment/ —
the SPA calls /api/news/audio/ and /api/news/stories/<id>/
instead. Old GETs to those URLs fall through to the catch-all
shell (React Router sends them to /news/) and non-GETs get a
404 from react_app_public — the retired POST /news/
preferences/ form action can no longer answer with HTML."""
from functools import partial

from django.urls import path

from industry_analyser.views import react_app_public
from . import views

app_name = 'news'

react_app_news = partial(
    react_app_public, entry='news', title='News',
    landing_desc='Daily digest of Latvian news across outlets.',
)

urlpatterns = [
    path('', react_app_news, name='digest-list'),
    # preferences/ MUST precede '<str:date>/' — 'str' would
    # swallow 'preferences' as a date (same subtlety the old
    # file documented for audio/ too; React Router ranks the
    # static /preferences route above /:date client-side, so
    # the client needs no extra care).
    path('preferences/', react_app_news, name='preferences'),
    # Binary FileResponse stays a Django view. Multi-segment —
    # '<str:date>/' can't collide; must precede <path:subpath>.
    path(
        'article/<int:pk>/audio/',
        views.article_audio,
        name='article-audio',
    ),
    path('<str:date>/', react_app_news, name='digest-detail'),
    # No trailing slash — matches 'x' and 'x/'; non-GET 404s.
    path('<path:subpath>', react_app_news, name='spa_subpath'),
]

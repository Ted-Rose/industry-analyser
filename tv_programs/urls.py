"""tv URLconf — React SPA shell.

Stage 3 cutover: every GET/HEAD path under /tv/ serves the shared
SPA shell (Vite entry 'tv') and React Router resolves the page
client-side. The route names stay so reverse() callers keep working
('tv_programs:program_list' is linked from the scrape_jobs
dashboard; 'tv_programs:spoki_page' now resolves to the shell and
the client route fetches GET /api/tv/spoki-page/).

Retired: the `react/<uuid>/<reaction>/` POST form action — the SPA
calls POST /api/tv/shows/<id>/react/<reaction>/ instead. Old GET
requests to that URL fall through to the catch-all shell (React
Router sends them to /tv/) and POSTs get a 404 from
react_app_public, so retired mutation URLs can't answer with HTML.
"""
from functools import partial

from django.urls import path

from industry_analyser.views import react_app_public

app_name = 'tv_programs'

react_app_tv = partial(react_app_public, entry='tv', title='TV')

urlpatterns = [
    # '' is the program feed — the name is kept for
    # scrape_jobs/dashboard.html's {% url 'tv_programs:program_list' %}.
    path('', react_app_tv, name='program_list'),
    path('spoki-page/', react_app_tv, name='spoki_page'),
    # No trailing slash on <path:subpath> — it matches both 'x' and
    # 'x/', so client routes don't depend on an APPEND_SLASH hop.
    path('<path:subpath>', react_app_tv, name='spa_subpath'),
]

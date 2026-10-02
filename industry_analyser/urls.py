"""
URL configuration for industry_analyser project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from functools import partial

from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from fetcher import views as fetcher
from fetcher.api import router as vacancies_router
from tv_programs.api import router as tv_router
from classified_ads.api import router as classified_ads_router
from scrape_jobs.api import router as dashboard_router
from industry_analyser import views as project_views
from industry_analyser.api import api
from industry_analyser.views import react_app, react_app_public

api.add_router('/vacancies/', vacancies_router)
api.add_router('/tv/', tv_router)
# The classified_ads SPA's URL base is hyphenated /classified-ads/;
# the router mount follows it so spa_url_for's /api/<x>/ → /<x>/
# login-next rewrite stays correct.
api.add_router('/classified-ads/', classified_ads_router)
# The dashboard SPA mounts at the site root — SPA_BASES maps
# /api/dashboard/* 401 login_urls back to '/'.
api.add_router('/dashboard/', dashboard_router)

# The vacancies SPA owns both /vacancies/* and /companies/* — the
# company pages are routes of the same React app (entry
# 'vacancies'). Every GET/HEAD path renders the shell and React
# Router resolves the page client-side; non-GET requests 404.
react_app_vacancies = partial(
    react_app_public, entry='vacancies', title='Vacancies'
)
react_app_companies = partial(
    react_app_public, entry='vacancies', title='Companies'
)
# The dashboard is the only login-required SPA (the template page it
# replaces was @login_required) — react_app, not the public variant.
react_app_dashboard = partial(
    react_app, entry='dashboard', title='Dashboard'
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('manifest.json', fetcher.pwa_manifest, name='pwa_manifest'),
    path('sw.js', fetcher.pwa_service_worker, name='pwa_service_worker'),
    # Shared ninja API — mounted before the app routes so /api/* can
    # never be swallowed by the root catch-all SPA mount.
    path('api/', api.urls),
    # The dashboard SPA owns the site root — the name 'home' is kept
    # so reverse('home') still resolves to '/'.
    path('', react_app_dashboard, name='home'),
    # Vacancies SPA. Route names stay so reverse()/{% url %} callers
    # keep working ('find_vacancies' reversed to /vacancies/).
    path('vacancies/', react_app_vacancies, name='find_vacancies'),
    # No trailing slash on <path:subpath> — it matches both 'x' and
    # 'x/', so client routes don't depend on an APPEND_SLASH hop.
    path(
        'vacancies/<path:subpath>',
        react_app_vacancies,
        name='vacancies_subpath',
    ),
    path('companies/', react_app_companies, name='companies'),
    # Named <uuid:pk> route keeps {% url 'company_detail' pk %}
    # resolving to /companies/<pk>/, which the SPA router serves.
    # Must precede the <path:subpath> catch-all.
    path(
        'companies/<uuid:pk>/',
        react_app_companies,
        name='company_detail',
    ),
    path(
        'companies/<path:subpath>',
        react_app_companies,
        name='companies_subpath',
    ),
    # The accounts stub page is retired — 301 to the dashboard; the
    # name is kept so any reverse('accounts') caller still resolves.
    path(
        'accounts/',
        RedirectView.as_view(url='/', permanent=True),
        name='accounts',
    ),
    path(
        'add_keyword/',
        fetcher.add_keyword_redirect,
        name='add_keyword',
    ),
    path('tv/', include('tv_programs.urls', namespace='tv_programs')),
    path(
        'classified-ads/',
        include('classified_ads.urls', namespace='classified_ads'),
    ),
]

if settings.DEBUG:
    # Chrome DevTools probes this on every load while open; an empty
    # JSON object keeps 404 WARNING noise out of the runserver log.
    urlpatterns.append(path(
        '.well-known/appspecific/com.chrome.devtools.json',
        project_views.chrome_devtools_probe,
    ))

# Terminal 404 drains for prefixes owned by earlier mounts. A
# Resolver404 raised inside the 'api/' or 'admin/' mounts (or a
# whitenoise pass-through under 'static/') falls through to the next
# pattern — without these, misses like /api/<typo> would serve the
# root SPA shell, and unslashed hits like /api/dashboard would lose
# the APPEND_SLASH redirect CommonMiddleware only applies to 404s.
# Legit routes under those prefixes resolve earlier, so order is safe.
for _prefix in ('api', 'admin', 'static'):
    urlpatterns.append(path(_prefix, project_views.terminal_404))
    urlpatterns.append(path(
        f'{_prefix}/<path:subpath>',
        project_views.terminal_404,
    ))

# The root dashboard catch-all must be the very LAST pattern — it
# would shadow anything appended after it (including the DEBUG-only
# .well-known probe above). No trailing slash on <path:subpath> — it
# matches 'x' and 'x/', so client routes don't depend on an
# APPEND_SLASH hop; non-GET/HEAD requests 404 via react_app.
urlpatterns.append(path(
    '<path:subpath>',
    react_app_dashboard,
    name='dashboard_subpath',
))

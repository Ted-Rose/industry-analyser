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
from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from fetcher import views as fetcher
from accounts import views as accounts
from scrape_jobs import views as scrape_jobs
from industry_analyser import views as project_views
from industry_analyser.api import api

urlpatterns = [
    path('admin/', admin.site.urls),
    path('manifest.json', fetcher.pwa_manifest, name='pwa_manifest'),
    path('sw.js', fetcher.pwa_service_worker, name='pwa_service_worker'),
    # Shared ninja API — mounted before the app routes so /api/* can
    # never be swallowed by a future catch-all SPA mount.
    path('api/', api.urls),
    path('', scrape_jobs.dashboard, name='home'),
    path('vacancies/', fetcher.find_vacancies, name='find_vacancies'),
    path('companies/', fetcher.company_list, name='companies'),
    path(
        'companies/<uuid:pk>/',
        fetcher.company_detail,
        name='company_detail',
    ),
    path('accounts/', accounts.accounts, name='accounts'),
    path('add_keyword/', fetcher.add_keyword, name='add_keyword'),
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

from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_control

from .scraper import load_portals_config


# Bump on every shipped frontend change (new SPA bundle, sw.js edit)
# to force clients off the old service-worker cache.
PWA_CACHE_VERSION = 'v6'


def pwa_manifest(request):
    return render(
        request,
        'fetcher/manifest.json',
        content_type='application/json',
    )


@cache_control(no_cache=True)
def pwa_service_worker(request):
    return render(
        request,
        'fetcher/sw.js',
        {'cache_version': PWA_CACHE_VERSION},
        content_type='application/javascript',
    )


def _file_url(file_id):
    """files-service URL for a stored file id (logo/cover/
    gallery), or None when no portal config provides files_href."""
    if not file_id:
        return None
    try:
        portals = load_portals_config()
    except Exception:
        return None
    for cfg in portals.values():
        if cfg.get('base_url') and cfg.get('files_href'):
            return cfg['base_url'] + cfg['files_href'] + file_id
    return None


def add_keyword_redirect(request):
    """Retired /add_keyword/ password form → the vacancies SPA's
    keywords route. Non-GET/HEAD 404s like every retired form URL —
    mutations live under /api/vacancies/."""
    if request.method not in ('GET', 'HEAD'):
        raise Http404
    return redirect('/vacancies/keywords', permanent=True)

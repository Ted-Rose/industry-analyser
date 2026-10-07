"""Startup checks guarding the React SPA shell's failure modes.

Both warnings target the same symptom — a page stuck on "Loading
React app…": dev-mode asset URLs pointing at a vite that isn't
serving this project (W001), and a collectstatic output older than
the last frontend build (W002).
"""
import json
import os
import urllib.request

from django.conf import settings
from django.core.checks import Warning, register


def _vite_config():
    return settings.DJANGO_VITE.get('default', {})


def _manifest_path():
    return _vite_config().get(
        'manifest_path',
        os.path.join(settings.BASE_DIR, 'frontend_dist',
                     'manifest.json'),
    )


@register()
def vite_dev_server_probe(app_configs, **kwargs):
    """VITE_DEV=1 makes {% vite_asset %} emit dev-server URLs — when
    nothing (or a foreign project) answers on the port, the SPA
    renders its shell but the bundle never arrives."""
    config = _vite_config()
    if not config.get('dev_mode'):
        return []
    port = config.get('dev_server_port', 5173)
    url = (f'http://localhost:{port}/static/src/dashboard/'
           'main.tsx')
    try:
        with urllib.request.urlopen(url, timeout=1):
            return []
    except Exception:
        return [Warning(
            f'vite dev server not serving this project on :{port} '
            f'(probe {url} failed) — SPA pages will sit on '
            '"Loading React app…". Start vite with `./dev.sh` or '
            '`npm run dev --prefix frontend`.',
            id='industry_analyser.W001',
        )]


@register()
def collected_frontend_fresh(app_configs, **kwargs):
    """With DEBUG off, whitenoise serves /static/ from STATIC_ROOT —
    a frontend build newer than the last collectstatic leaves the
    manifest pointing at hashed files that 404."""
    if _vite_config().get('dev_mode') or settings.DEBUG:
        return []
    if getattr(settings, 'WHITENOISE_USE_FINDERS', False):
        return []  # finders serve frontend_dist/ directly
    try:
        with open(_manifest_path()) as manifest_file:
            manifest = json.load(manifest_file)
    except (OSError, ValueError):
        return []  # spa_shell's manifest_ready banner covers this
    static_root = settings.STATIC_ROOT
    missing = [
        chunk['file'] for chunk in manifest.values()
        if isinstance(chunk, dict) and chunk.get('file')
        and not os.path.isfile(os.path.join(static_root,
                                            chunk['file']))
    ]
    if not missing:
        return []
    return [Warning(
        f'{len(missing)} frontend_dist asset(s) missing under '
        f'STATIC_ROOT ({missing[0]}, …) — the manifest advertises '
        'files whitenoise cannot serve, so SPA pages sit on '
        '"Loading React app…". Run '
        '`python manage.py collectstatic` or use `./dev.sh`.',
        id='industry_analyser.W002',
    )]

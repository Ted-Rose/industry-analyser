"""Shared SPA shell helpers (Stage 0 of the React+Vite migration).

Ported from django-apps' django_apps/views.py. One shell view renders
<div id="root"> plus the {% vite_asset %} tags for a given Vite entry;
`react_app` (login-required) and `react_app_public` wrap it so every
app mount shares the same GET/HEAD→shell, non-GET→404 contract.
"""
import json
import os
import re

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import (
    Http404,
    HttpResponsePermanentRedirect,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.urls import is_valid_path
from django.views.decorators.csrf import ensure_csrf_cookie


def chrome_devtools_probe(request):
    """Chrome DevTools GETs this while open to detect workspace
    integration — an empty object keeps the 404 WARNING noise out of
    the runserver log. Routed only when DEBUG."""
    return JsonResponse({})


def terminal_404(request, subpath=''):
    """Drain for misses under prefixes owned by earlier mounts
    (/api/, /admin/, /static/), routed just before the root
    <path:subpath> catch-all.

    Django's resolver catches a Resolver404 raised inside an
    include()/api.urls mount and keeps iterating — without these
    patterns a miss like /api/<typo> would fall through to the SPA
    shell. The drain itself makes an unslashed path "valid" to
    is_valid_path(), which would suppress CommonMiddleware's
    APPEND_SLASH redirect — so the view replicates it: when the
    slashed variant resolves to a real view (not back to this drain),
    301 there just as the middleware would have.
    """
    if (
        settings.APPEND_SLASH
        and request.method in ('GET', 'HEAD')
        and not request.path_info.endswith('/')
    ):
        match = is_valid_path(f'{request.path_info}/')
        if (
            match
            and match.func is not terminal_404
            and getattr(match.func, 'should_append_slash', True)
        ):
            target = f'{request.path_info}/'
            if request.GET:
                target = f'{target}?{request.GET.urlencode()}'
            return HttpResponsePermanentRedirect(target)
    raise Http404


# SPA entry names map to folders under frontend/src/ and keys in
# manifest.json — restrict them to plain lowercase identifiers so a
# future mount deriving `entry` from a URL segment can't traverse or
# 500 on {% vite_asset %} (hyphenated URL bases like /classified-ads/
# map to entry 'classified_ads').
SPA_ENTRY_RE = re.compile(r'[a-z0-9_]+')


def _manifest_has_entry(manifest_path, entry_key):
    """True only if manifest.json exists AND still lists `entry_key`.

    A stale/partial build can leave a manifest that lacks the entry —
    {% vite_asset %} would raise DjangoViteAssetNotFoundError (500)
    on it, so the caller degrades to the diagnostic warning instead.
    A corrupt manifest degrades the same way.
    """
    try:
        with open(manifest_path, 'r') as manifest_file:
            return entry_key in json.load(manifest_file)
    except (OSError, ValueError):
        return False


def _spa_shell(request, entry, title=''):
    """Undecorated core: render the shared React SPA shell.

    `entry` is the app folder under frontend/src/ (e.g. 'vacancies' →
    src/vacancies/main.tsx). `manifest_ready` tells the template
    whether {% vite_asset %} is safe to call: always in dev mode
    (VITE_DEV=1, where django-vite hits the dev server and never reads
    the manifest), or in prod only when manifest.json exists and
    contains the entry key. Otherwise the page shows a diagnostic
    instead of crashing.
    """
    if not SPA_ENTRY_RE.fullmatch(entry):
        raise Http404(f'Unknown SPA entry: {entry}')
    vite_entry = f'src/{entry}/main.tsx'
    vite_config = settings.DJANGO_VITE.get('default', {})
    manifest_path = vite_config.get(
        'manifest_path',
        os.path.join(settings.BASE_DIR, 'frontend_dist',
                     'manifest.json'),
    )
    return render(request, 'spa_shell.html', {
        'title': title,
        'vite_entry': vite_entry,
        'manifest_ready': (
            vite_config.get('dev_mode')
            or _manifest_has_entry(manifest_path, vite_entry)
        ),
        'bootstrap': {
            'user': request.user.get_username() or None,
        },
    })


@login_required
@ensure_csrf_cookie
def spa_shell(request, entry, title=''):
    """Login-required shell — for apps whose pages need auth (e.g.
    the root dashboard)."""
    return _spa_shell(request, entry, title=title)


@ensure_csrf_cookie
def spa_shell_public(request, entry, title=''):
    """Public shell — most industry-analyser pages are public today,
    so their SPA mounts must not bounce anonymous visitors to login."""
    return _spa_shell(request, entry, title=title)


def react_app(request, entry, title='', subpath='', **kwargs):
    """React SPA shell shared by every login-required app mount.

    Mount with functools.partial (or a thin wrapper) binding `entry`
    (the frontend/src/<entry>/ folder and vite input key) and
    `title`, e.g.::

        path('', partial(react_app, entry='dashboard',
                         title='Dashboard'))
        path('<path:subpath>',
             partial(react_app, entry='dashboard', title='Dashboard'))

    Every GET/HEAD path under the mount renders the shell and React
    Router resolves the page client-side; `subpath` is captured by
    <path:subpath> catch-alls and intentionally unused.

    Non-GET/HEAD requests 404: retired template-mutation URLs must
    not answer with the HTML shell — mutations live under /api/.
    """
    if request.method not in ('GET', 'HEAD'):
        raise Http404
    return spa_shell(request, entry=entry, title=title)


def react_app_public(request, entry, title='', subpath='', **kwargs):
    """Same contract as `react_app` but without login_required — for
    apps whose pages are public today (vacancies, tv, classified-ads).
    Mutations still require auth at the /api/ layer.

    `subpath` is captured by <path:subpath> catch-alls; `kwargs`
    swallows any named converters (e.g. <uuid:pk> on a named route
    kept for reverse() callers) — React Router resolves the page
    either way.
    """
    if request.method not in ('GET', 'HEAD'):
        raise Http404
    return spa_shell_public(request, entry=entry, title=title)


def app_redirect(request, base, subpath=''):
    """301 /<base>/app/<subpath> → /<base>/<subpath>.

    Used for the strangler-mount cleanup: while an SPA is staged at
    /<base>/app/ the mount serves `react_app`; after cutover the app
    paths 301 here so old links/bookmarks keep working without
    serving the shell twice. `base` tolerates missing slashes
    ('vacancies' and '/vacancies/' behave the same). Deliberately NOT
    login_required: anonymous users are bounced to login by the
    destination page after the redirect, avoiding a double hop.
    """
    prefix = f"/{base.strip('/')}/" if base.strip('/') else '/'
    target = f'{prefix}{subpath}'
    if request.GET:
        target = f'{target}?{request.GET.urlencode()}'
    return redirect(target, permanent=True)

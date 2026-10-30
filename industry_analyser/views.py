"""Shared SPA shell helpers (Stage 0 of the React+Vite migration).

Ported from django-apps' django_apps/views.py. One shell view renders
<div id="root"> plus the {% vite_asset %} tags for a given Vite entry;
`react_app` (staff-required) and `react_app_public` wrap it so every
app mount shares the same GET/HEAD→shell, non-GET→404 contract.
"""
import json
import os
import re
from functools import partial

from django.conf import settings
from django.contrib.admin.views.decorators import (
    staff_member_required,
)
from django.http import (
    Http404,
    HttpResponsePermanentRedirect,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.urls import URLPattern, get_resolver, is_valid_path
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

# SPA entries still themed by the Bootstrap CDN links — an app
# leaves this set only when EVERY route in it has been migrated
# to the design system (the classified_ads split stays on until
# its second migration PR; the accounts SPA landed on master
# with Bootstrap markup and migrates with the cleanup PR).
# spa_shell.html wraps both CDN <link>s in
# {% if legacy_bootstrap %}.
LEGACY_BOOTSTRAP_ENTRIES = {
    'accounts',
    'classified_ads',
}


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
        'legacy_bootstrap': entry in LEGACY_BOOTSTRAP_ENTRIES,
        'manifest_ready': (
            vite_config.get('dev_mode')
            or _manifest_has_entry(manifest_path, vite_entry)
        ),
        'bootstrap': {
            'user': request.user.get_username() or None,
            # The auto-discovered app mounts + auth flags — the
            # SPA TopNav builds its AppSwitcher and login/logout
            # state off these instead of a hardcoded list (same
            # contract the / landing page renders).
            'apps': _landing_entries(),
            'is_authenticated': request.user.is_authenticated,
            'is_staff': getattr(request.user, 'is_staff', False),
            # Web Sentry config ships inside the page — the SPA reads
            # it before createRoot, so no VITE_* build vars are
            # needed. Empty dsn leaves the browser SDK uninitialized.
            'sentry': {
                'dsn': settings.SENTRY_WEB_DSN,
                'environment': settings.SENTRY_ENVIRONMENT,
                'release': settings.SENTRY_RELEASE,
            },
        },
    })


@staff_member_required
@ensure_csrf_cookie
def spa_shell(request, entry, title=''):
    """Staff-required shell — for apps whose pages are staff-only
    (the dashboard and receipts SPAs). staff_member_required
    bounces anonymous AND authenticated non-staff visitors to the
    admin login, which explains the missing staff rights."""
    return _spa_shell(request, entry, title=title)


@ensure_csrf_cookie
def spa_shell_public(request, entry, title=''):
    """Public shell — most industry-analyser pages are public today,
    so their SPA mounts must not bounce anonymous visitors to login."""
    return _spa_shell(request, entry, title=title)


def react_app(request, entry, title='', subpath='', **kwargs):
    """React SPA shell shared by every staff-required app mount.

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
    """Same contract as `react_app` but without staff_member_required
    — for apps whose pages are public today (vacancies, tv,
    classified-ads, accounts). Mutations still require auth at the
    /api/ layer.

    `subpath` is captured by <path:subpath> catch-alls; `kwargs`
    swallows any named converters (e.g. <uuid:pk> on a named route
    kept for reverse() callers) — React Router resolves the page
    either way.
    """
    if request.method not in ('GET', 'HEAD'):
        raise Http404
    return spa_shell_public(request, entry=entry, title=title)


# --- Landing page ---

# Top-level routes that never become landing entries: infra
# mounts (the JSON API, admin, the whitenoise pass-through) and
# the accounts utility SPA (auth pages, not a mini-app).
# Everything else is discovered — a new app mount needs no edit
# here.
_LANDING_SKIP_ROUTES = {'api/', 'admin/', 'static/', 'accounts/'}


def _is_spa_partial(callback):
    """True when `callback` is a functools.partial of one of the
    shared SPA shells (the way every SPA mount is wired in
    urlpatterns)."""
    return (
        isinstance(callback, partial)
        and callback.func in (react_app, react_app_public)
    )


def _spa_entry_fields(callback):
    """Landing entry fields off an SPA shell partial.

    `title` is the page title kwarg every mount already binds;
    `landing_title`/`landing_desc` are optional display overrides
    and `landing_cta` promotes the entry to the prominent
    call-to-action slot — all swallowed by react_app's **kwargs.
    The auth flag follows from which shell was bound — react_app
    mounts are staff-required."""
    keywords = callback.keywords
    return {
        'title': (
            keywords.get('landing_title')
            or keywords.get('title', '')
        ),
        'desc': keywords.get('landing_desc', ''),
        'cta': bool(keywords.get('landing_cta')),
        'login_required': callback.func is react_app,
    }


def _resolver_entry_fields(resolver, route):
    """Title/auth/desc for an include() mount.

    The mounted urlconf's first SPA-shell partial supplies them
    (tv, receipts, classified_ads all bind `title` there); a mount
    whose urlconf serves plain-template views instead (news) gets
    a humanized path segment and is public. An empty urlconf is
    not a page — None skips it.
    """
    inner = resolver.url_patterns
    if not inner:
        return None
    for inner_pattern in inner:
        if isinstance(inner_pattern, URLPattern) and _is_spa_partial(
            inner_pattern.callback
        ):
            return _spa_entry_fields(inner_pattern.callback)
    return {
        'title': (
            route.rstrip('/')
            .replace('-', ' ')
            .replace('_', ' ')
            .title()
        ),
        'desc': '',
        'cta': False,
        'login_required': False,
    }


def _landing_entries():
    """Auto-discover the top-level app mounts for the landing page.

    Introspects the root urlconf — per request, never at import
    time (urls.py imports this module, so touching the resolver at
    module scope would recurse). Only single-segment literal
    routes ending in '/' qualify: converters ('companies/<uuid:pk>/'),
    the root '' itself, the <path:subpath> drains, file routes
    (manifest.json, sw.js) and the _LANDING_SKIP_ROUTES prefixes
    are all skipped. A newly added top-level mount — SPA partial
    or include() — appears on / without touching this view.
    """
    entries = []
    for url_pattern in get_resolver().url_patterns:
        route = getattr(url_pattern.pattern, '_route', '')
        if (
            '<' in route
            or route in _LANDING_SKIP_ROUTES
            or not route.endswith('/')
            or '/' in route[:-1]
        ):
            continue
        if isinstance(url_pattern, URLPattern):
            if not _is_spa_partial(url_pattern.callback):
                continue
            fields = _spa_entry_fields(url_pattern.callback)
        else:
            fields = _resolver_entry_fields(url_pattern, route)
            if fields is None:
                continue
        entries.append({'url': f'/{route}', **fields})
    return entries


def landing(request, subpath=''):
    """Public landing page at / — a directory of the project's
    mini-apps, auto-discovered via _landing_entries().

    Also serves the terminal <path:subpath> catch-all: unknown
    paths render the directory instead of a bare 404 (the
    dashboard SPA the catch-all used to mount has only an index
    route — no client deep links worth preserving).
    """
    if request.method not in ('GET', 'HEAD'):
        raise Http404
    entries = _landing_entries()
    return render(request, 'landing.html', {
        'apps': [e for e in entries if not e['cta']],
        'cta_apps': [e for e in entries if e['cta']],
    })


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

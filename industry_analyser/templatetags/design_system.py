"""Design-system template tags ({% load design_system %}).

{% ds_head %} emits the <link> for the built design-system CSS
entries (the `site` bundle — Tailwind + tokens + component
classes for Django-rendered pages). Unlike {% vite_asset %} it
is meant for CSS-only entries, and it degrades to an empty
string when the manifest or the entry is missing — landing and
news must keep working (unstyled) instead of 500ing on a stale
frontend_dist (plan §11.2).
"""
import json
import os
from urllib.parse import urljoin

from django import template
from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.utils.html import format_html

register = template.Library()

# Manifest keys for the CSS-only rollup inputs in
# frontend/vite.config.ts.
_DS_ENTRIES = {
    'site': 'src/shared/styles/site.css',
    'admin': 'src/shared/styles/admin.css',
}


def _vite_config():
    return settings.DJANGO_VITE.get('default', {})


def _manifest_entry(entry_path):
    """The manifest dict for `entry_path`, or {} when the
    manifest is missing/corrupt or no longer lists the entry."""
    manifest_path = _vite_config().get(
        'manifest_path',
        os.path.join(settings.BASE_DIR, 'frontend_dist',
                     'manifest.json'),
    )
    try:
        with open(manifest_path, 'r') as manifest_file:
            entry = json.load(manifest_file).get(entry_path)
    except (OSError, ValueError):
        return {}
    return entry if isinstance(entry, dict) else {}


def _dev_server_url(entry_path):
    """Dev-server asset URL — mirrors django-vite's
    get_dev_server_url(): {protocol}://{host}:{port}
    + urljoin(STATIC_URL, static_url_prefix) + path."""
    config = _vite_config()
    protocol = config.get('dev_server_protocol', 'http')
    host = config.get('dev_server_host', 'localhost')
    port = config.get('dev_server_port', 5173)
    static_base = urljoin(
        settings.STATIC_URL, config.get('static_url_prefix', '')
    )
    if not static_base.endswith('/'):
        static_base += '/'
    return urljoin(
        f'{protocol}://{host}:{port}',
        urljoin(static_base, entry_path),
    )


@register.simple_tag
def ds_head(entry='site'):
    """<link rel="stylesheet"> for a design-system CSS entry.

    `entry` is the vite input name ('site' — the default — or
    'admin'). In vite dev mode the link points at the dev server;
    in production it resolves through frontend_dist/manifest.json
    and renders nothing when the entry is absent, so a missing
    build degrades the page to unstyled HTML rather than a 500.
    """
    entry_path = _DS_ENTRIES.get(entry)
    if entry_path is None:
        return ''
    if _vite_config().get('dev_mode'):
        return format_html(
            '<link rel="stylesheet" href="{}">',
            _dev_server_url(entry_path),
        )
    file = _manifest_entry(entry_path).get('file')
    if not file:
        return ''
    return format_html(
        '<link rel="stylesheet" href="{}">',
        staticfiles_storage.url(file),
    )

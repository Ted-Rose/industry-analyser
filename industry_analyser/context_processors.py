"""Global template context — the top-nav app directory.

`global_nav` feeds _topbar.html (the server-rendered twin of the
SPA TopNav, plan §5) on every plain-template page — landing and
news — so individual views stay untouched. Auth state comes from
the stock `request`/`user` context; this only adds `nav_apps`.
"""
from .views import _landing_entries


def global_nav(request):
    """`nav_apps` — the same auto-discovered mounts the landing
    page lists (views._landing_entries)."""
    return {'nav_apps': _landing_entries()}

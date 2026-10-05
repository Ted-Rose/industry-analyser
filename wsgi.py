"""Vercel entrypoint — the Python runtime auto-detects `wsgi.py` at
the repo root and loads the top-level `app`/`application` callable.
`tool.vercel.entrypoint` in pyproject.toml alone was not enough: the
deployment shipped as a raw static serve of the repo (every path
edge-404'd with X-Vercel-Error: NOT_FOUND and no function existed).
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE', 'industry_analyser.settings'
)

app = get_wsgi_application()
application = app

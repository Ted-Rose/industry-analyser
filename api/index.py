"""Vercel entrypoint — file-based function convention.

Framework preset detection (manage.py / tool.vercel.entrypoint /
root wsgi.py) produced a static-only deployment on this project —
every path edge-404'd. A .py file under api/ becomes a Vercel
Function without any framework detection, and the catch-all rewrite
in vercel.json routes all traffic here. Rewrites don't alter the
path seen by user code, so Django resolves the original URL.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE', 'industry_analyser.settings'
)

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
application = app

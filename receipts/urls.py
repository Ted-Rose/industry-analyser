"""receipts URLconf — React SPA shell for the spending dashboard.

Mounted at /receipts/ in industry_analyser/urls.py. Stage 3
cutover: every GET/HEAD path under /receipts/ serves the shared
SPA shell (Vite entry 'receipts') and React Router resolves the
page client-side; non-GET requests 404. The 'dashboard' name is
kept so reverse('receipts:dashboard') callers keep resolving.

Unlike the public SPAs the shell mounts `react_app`
(staff-required) — the receipts page IS the data, so
anonymous and non-staff visitors bounce to /admin/login/
before the bundle loads.
"""
from functools import partial

from django.urls import path

from industry_analyser.views import react_app

app_name = 'receipts'

react_app_receipts = partial(
    react_app, entry='receipts', title='Receipts')

urlpatterns = [
    path('', react_app_receipts, name='dashboard'),
    # No trailing slash on <path:subpath> — it matches both 'x' and
    # 'x/', so client routes don't depend on an APPEND_SLASH hop.
    path('<path:subpath>', react_app_receipts),
]

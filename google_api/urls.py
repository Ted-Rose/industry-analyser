from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'google_api'

urlpatterns = [
    # /google/ starts the OAuth flow — the landing page's
    # auto-discovered "Google" entry links here.
    path(
        '',
        RedirectView.as_view(url='/google/login/'),
        name='index',
    ),
    path('login/', views.login_view, name='login'),
    # The landing <path:subpath> catch-all swallows slashless
    # requests before APPEND_SLASH can redirect — bounce
    # /google/login explicitly.
    path(
        'login',
        RedirectView.as_view(url='/google/login/'),
        name='login_noslash',
    ),
    # No trailing slash — must match the redirect URI registered
    # on the OAuth client ({BASE_URL}/google/callback) exactly.
    path('callback', views.callback, name='callback'),
]

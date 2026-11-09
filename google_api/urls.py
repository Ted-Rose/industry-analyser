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
    path('signin/', views.signin_view, name='signin'),
    # Same slashless drain as login — the landing catch-all
    # swallows /google/signin before APPEND_SLASH can redirect.
    path(
        'signin',
        RedirectView.as_view(url='/google/signin/'),
        name='signin_noslash',
    ),
    # No trailing slash — must match the redirect URI registered
    # on the OAuth client ({BASE_URL}/google/callback) exactly.
    path('callback', views.callback, name='callback'),
]

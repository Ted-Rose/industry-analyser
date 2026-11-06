from django.urls import path

from . import views

app_name = 'google_api'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    # No trailing slash — must match the redirect URI registered
    # on the OAuth client ({BASE_URL}/google/callback) exactly.
    path('callback', views.callback, name='callback'),
]

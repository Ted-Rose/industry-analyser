"""news URLconf — plain Django template digest pages (no React,
no ninja API). Mounted at /news/ in industry_analyser/urls.py."""
from django.urls import path

from . import views

app_name = 'news'

urlpatterns = [
    path('', views.digest_list, name='digest-list'),
    path('<str:date>/', views.digest_detail, name='digest-detail'),
]

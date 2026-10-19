"""receipts URLconf — the spending dashboard.

Mounted at /receipts/ in industry_analyser/urls.py.
"""
from django.urls import path

from . import views

app_name = 'receipts'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
]

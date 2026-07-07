from django.urls import path

from . import views

app_name = 'classified_ads'

urlpatterns = [
    path('', views.ads_table, name='ads_table'),
]

from django.urls import path

from . import views

app_name = 'classified_ads'

urlpatterns = [
    path('', views.index, name='index'),
    path('ads/', views.ads_table, name='ads_table'),
    path('regions/', views.region_config, name='region_config'),
    path('regions/stats/', views.region_stats, name='region_stats'),
    path(
        'regions/stats/<int:region_id>/children/',
        views.region_stats_children,
        name='region_stats_children',
    ),
]

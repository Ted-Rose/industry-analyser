from django.urls import path

from . import views

app_name = 'classified_ads'

urlpatterns = [
    path('', views.index, name='index'),
    path(
        'apartments/',
        views.apartment_ads_table,
        name='apartment_ads_table'
    ),
    path(
        'apartments/rent/',
        views.apartment_rent_ads_table,
        name='apartment_rent_ads_table'
    ),
    path(
        'apartments/sale/',
        views.apartment_sale_ads_table,
        name='apartment_sale_ads_table'
    ),
    path('regions/', views.region_config, name='region_config'),
    path(
        'apartments/regions/stats/',
        views.apartment_region_stats,
        name='apartment_region_stats'
    ),
    path(
        'apartments/regions/stats/<int:region_id>/children/',
        views.apartment_region_stats_children,
        name='apartment_region_stats_children',
    ),
    path(
        'apartments/regions/<int:region_id>/ads/',
        views.apartment_region_ads_list,
        name='apartment_region_ads_list',
    ),
]

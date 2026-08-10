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
    path(
        'apartments/regions/config/',
        views.apartment_region_config,
        name='apartment_region_config'
    ),
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
    path(
        'houses/',
        views.house_ads_table,
        name='house_ads_table'
    ),
    path(
        'houses/rent/',
        views.house_rent_ads_table,
        name='house_rent_ads_table'
    ),
    path(
        'houses/sale/',
        views.house_sale_ads_table,
        name='house_sale_ads_table'
    ),
    path(
        'houses/regions/config/',
        views.house_region_config,
        name='house_region_config'
    ),
    path(
        'houses/regions/stats/',
        views.house_region_stats,
        name='house_region_stats'
    ),
    path(
        'houses/regions/stats/<int:region_id>/children/',
        views.house_region_stats_children,
        name='house_region_stats_children',
    ),
    path(
        'houses/regions/<int:region_id>/ads/',
        views.house_region_ads_list,
        name='house_region_ads_list',
    ),
    path(
        'daily-sightings/',
        views.daily_sightings_report,
        name='daily_sightings_report'
    ),
]

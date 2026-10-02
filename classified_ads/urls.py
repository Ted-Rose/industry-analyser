"""classified_ads URLconf — React SPA cutover.

Every path renders the classified_ads SPA shell (GET/HEAD → shell,
anything else → 404; mutations live under /api/classified-ads/).
React Router (basename '/classified-ads') resolves the page
client-side. All pre-cutover route names are kept so reverse()/
{% url 'classified_ads:…' %} callers (e.g. the scrape_jobs dashboard
linking 'index') keep working; patterns with converters keep their
explicit shape — the shell partial swallows the kwargs.
"""
from functools import partial

from django.urls import path

from industry_analyser.views import react_app_public

app_name = 'classified_ads'

# The public URL base is /classified-ads/ while the vite entry slug is
# 'classified_ads' (SPA_ENTRY_RE is [a-z0-9_]+ — hyphens illegal).
react_app_ads = partial(
    react_app_public, entry='classified_ads', title='Classified Ads'
)

urlpatterns = [
    path('', react_app_ads, name='index'),
    # Was a redirect to apartment_rent_ads_table — now the SPA shell;
    # the client route /apartments navigates to /apartments/rent.
    path('apartments/', react_app_ads, name='apartment_ads_table'),
    path(
        'apartments/rent/',
        react_app_ads,
        name='apartment_rent_ads_table',
    ),
    path(
        'apartments/sale/',
        react_app_ads,
        name='apartment_sale_ads_table',
    ),
    path(
        'apartments/regions/config/',
        react_app_ads,
        name='apartment_region_config',
    ),
    path(
        'apartments/regions/stats/',
        react_app_ads,
        name='apartment_region_stats',
    ),
    path(
        'apartments/regions/stats/<int:region_id>/children/',
        react_app_ads,
        name='apartment_region_stats_children',
    ),
    path(
        'apartments/regions/<int:region_id>/ads/',
        react_app_ads,
        name='apartment_region_ads_list',
    ),
    # Was a redirect to house_rent_ads_table — see apartments/ above.
    path('houses/', react_app_ads, name='house_ads_table'),
    path(
        'houses/rent/',
        react_app_ads,
        name='house_rent_ads_table',
    ),
    path(
        'houses/sale/',
        react_app_ads,
        name='house_sale_ads_table',
    ),
    path(
        'houses/regions/config/',
        react_app_ads,
        name='house_region_config',
    ),
    path(
        'houses/regions/stats/',
        react_app_ads,
        name='house_region_stats',
    ),
    path(
        'houses/regions/stats/<int:region_id>/children/',
        react_app_ads,
        name='house_region_stats_children',
    ),
    path(
        'houses/regions/<int:region_id>/ads/',
        react_app_ads,
        name='house_region_ads_list',
    ),
    path(
        'daily-sightings/',
        partial(
            react_app_public,
            entry='classified_ads',
            title='Daily Sightings Report',
        ),
        name='daily_sightings_report',
    ),
    path(
        'properties/apartments/',
        react_app_ads,
        name='apartment_property_list',
    ),
    path(
        'properties/apartments/<int:pk>/',
        react_app_ads,
        name='apartment_property_detail',
    ),
    path(
        'properties/houses/',
        react_app_ads,
        name='house_property_list',
    ),
    path(
        'properties/houses/<int:pk>/',
        react_app_ads,
        name='house_property_detail',
    ),
    # No trailing slash — matches 'x' and 'x/' so client routes don't
    # depend on an APPEND_SLASH hop.
    path('<path:subpath>', react_app_ads),
]

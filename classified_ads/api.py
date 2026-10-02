"""django-ninja router for the classified_ads SPA (mounted at
/api/classified-ads/ — the public URL base, not the app name;
SPA_ENTRY_RE forbids hyphens in entry slugs, not in API mounts).

GET ops are public (auth=None) — the template pages they replace were
public. POST /regions/config/ keeps the default django_auth (session +
CSRF): a deliberate tightening vs. the retired anonymous POST forms,
matching the migration README's "mutations keep django_auth" rule.

Query/aggregate logic mirrors the retired views in
classified_ads/views.py verbatim — the heavy `_compute_*_region_stats`
helpers moved here unchanged. Ad listers keep using the default
`objects` managers, which hide is_hidden rows (and
is_sale_misclassified rows on ApartmentForRent); the property detail
endpoint intentionally goes through `prop.linked_ads()`, which uses
`all_objects` — hidden/misclassified ads still belong to a property.
"""
from collections import defaultdict
from datetime import date, timedelta
from typing import List, Literal, Optional

from django.core.paginator import Paginator
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema
from pydantic import Field

from industry_analyser.api import ApiHttpError

from .models import (
    ApartmentForRent,
    ApartmentForRentSighting,
    ApartmentForSale,
    ApartmentForSaleSighting,
    ApartmentProperty,
    HouseForRent,
    HouseForRentSighting,
    HouseForSale,
    HouseForSaleSighting,
    HouseProperty,
    PROPERTY_MATCH_STATUS_CHOICES,
    Region,
)

router = Router()

ADS_PER_PAGE = 50
PROPERTIES_PER_PAGE = 50
STATS_DEFAULT_DAYS = 30
HOUSE_REGION_URL = '/homes-summer-residences/'

Kind = Literal['apartment', 'house']
Deal = Literal['rent', 'sale']
DEAL_TYPE_CHOICES = [('RENT', 'Rent'), ('SELL', 'Sell')]

PROPERTY_MODELS = {
    'apartment': (ApartmentProperty, 'Apartment'),
    'house': (HouseProperty, 'House'),
}

ADS_TABLE_MODELS = {
    ('apartment', 'rent'): ApartmentForRent,
    ('apartment', 'sale'): ApartmentForSale,
    ('house', 'rent'): HouseForRent,
    ('house', 'sale'): HouseForSale,
}

_MATCH_STATUS_LABELS = dict(PROPERTY_MATCH_STATUS_CHOICES)


# --- Schemas ---


class AdOut(Schema):
    """One row of an ads table — the union of the apartment and house
    columns the templates render (kind-specific fields stay null)."""
    id: int
    ad_id: str
    link: str
    district: str
    street_name: str
    street_no: str
    rooms: int
    size: float
    post_date: Optional[date]
    days_active: int
    deal: str
    # Apartments only.
    project: Optional[str]
    floor: Optional[int]
    max_floor: Optional[int]
    # Houses only.
    floors: Optional[int]
    land_area_sqm: Optional[float]
    # Sale models (and the region-ads table, which showed the
    # sale-equivalent columns for every deal type).
    price_per_sqm: float
    total_price: float
    # Rent models only — the ads tables' price columns for deal=rent.
    monthly_price: Optional[float]
    monthly_price_per_sqm: Optional[float]

    @staticmethod
    def resolve_project(obj):
        project = getattr(obj, 'project', None)
        return project.name if project else None

    @staticmethod
    def resolve_post_date(obj):
        return obj.post_date.date() if obj.post_date else None

    @staticmethod
    def resolve_days_active(obj):
        annotated = getattr(obj, 'days_active_count', None)
        if annotated is not None:
            return annotated
        return obj.days_active

    @staticmethod
    def resolve_deal(obj):
        # The old region-ads template tested `ad.deal_type` — an
        # attribute the models never had — so rent ads got the 'Sell'
        # badge. The SPA sends the real deal.
        return 'Rent' if hasattr(obj, 'monthly_price') else 'Sell'

    @staticmethod
    def resolve_floor(obj):
        return getattr(obj, 'floor', None)

    @staticmethod
    def resolve_max_floor(obj):
        return getattr(obj, 'max_floor', None)

    @staticmethod
    def resolve_floors(obj):
        return getattr(obj, 'floors', None)

    @staticmethod
    def resolve_land_area_sqm(obj):
        return getattr(obj, 'land_area_sqm', None)

    @staticmethod
    def resolve_monthly_price(obj):
        return getattr(obj, 'monthly_price', None)

    @staticmethod
    def resolve_monthly_price_per_sqm(obj):
        return getattr(obj, 'monthly_price_per_sqm', None)


class AdsFiltersOut(Schema):
    """Echo of the applied filters — the template's selected_* context."""
    district: str
    rooms: Optional[int]
    price_min: Optional[float]
    price_max: Optional[float]


class AdsTableOut(Schema):
    """One page of an ads table plus the filter option lists — a
    single fat endpoint per the rewrite plan."""
    ads: List[AdOut]
    page: int
    num_pages: int
    total_count: int
    has_next: bool
    has_previous: bool
    districts: List[str]
    room_choices: List[int]
    filters: AdsFiltersOut


class RegionNodeOut(Schema):
    """A region with its sub-regions — the config/checkbox trees."""
    id: int
    name: str
    url: str
    scrape_enabled: bool
    sub_regions: List['RegionNodeOut']

    @staticmethod
    def resolve_sub_regions(obj):
        return list(obj.sub_regions.all())


class RegionRefOut(Schema):
    id: int
    name: str


class RegionConfigOut(Schema):
    kind: str
    regions_tree: List[RegionNodeOut]
    enabled_count: int
    total_count: int


class RegionConfigIn(Schema):
    kind: Kind
    # POST body carries region URLs — the retired form submitted
    # name="regions" inputs with value="{{ region.url }}".
    regions: List[str] = Field(default_factory=list, max_length=10000)


class RegionConfigSavedOut(Schema):
    success: bool
    message: str


class RegionStatsRowOut(Schema):
    """One row of the region-stats table — a dict from
    _compute_*_region_stats with the Region nested under 'region'."""
    region: RegionRefOut
    total_ads: int
    total_properties: int
    avg_price_per_sqm: Optional[float]
    avg_size: Optional[float]
    avg_days_tracked: Optional[float]
    avg_days_on_market: Optional[float]


class RegionStatsOut(Schema):
    kind: str
    parent_regions: List[RegionRefOut]
    selected_ids: List[int]
    date_from: date
    date_to: date
    deal_type: str
    # Null until at least one region is checked — mirrors the
    # template's `{% if results is not None %}` gate.
    results: Optional[List[RegionStatsRowOut]]


class RegionStatsChildrenOut(Schema):
    kind: str
    parent_region: RegionRefOut
    date_from: date
    date_to: date
    deal_type: str
    results: List[RegionStatsRowOut]


class RegionAdsRegionOut(Schema):
    id: int
    name: str
    parent_id: Optional[int]
    parent_name: Optional[str]

    @staticmethod
    def resolve_parent_id(obj):
        return obj.parent_id

    @staticmethod
    def resolve_parent_name(obj):
        return obj.parent.name if obj.parent else None


class RegionAdsOut(Schema):
    kind: str
    region: RegionAdsRegionOut
    ads: List[AdOut]
    page: int
    num_pages: int
    total_count: int
    has_next: bool
    has_previous: bool
    date_from: date
    date_to: date
    deal_type: str


class DailySightingsRowOut(Schema):
    date: date
    apartment_rent: int
    apartment_sale: int
    apartment_total: int
    house_rent: int
    house_sale: int
    house_total: int
    grand_total: int


class SightingsRegionOut(Schema):
    """Parent region + flat sub-region list — the <optgroup> option
    tree of the retired sightings form."""
    id: int
    name: str
    sub_regions: List[RegionRefOut]

    @staticmethod
    def resolve_sub_regions(obj):
        return list(obj.sub_regions.all())


class DailySightingsOut(Schema):
    date_from: date
    date_to: date
    order: str
    selected_region: Optional[int]
    daily_data: List[DailySightingsRowOut]
    regions: List[SightingsRegionOut]


class PropertyRowOut(Schema):
    id: int
    district: str
    street_name: str
    street_no: str
    apartment_no: Optional[str]
    rooms: int
    size: float
    rent_ad_count: int
    sale_ad_count: int
    first_seen: date
    last_seen: date

    @staticmethod
    def resolve_apartment_no(obj):
        return getattr(obj, 'apartment_no', '') or ''

    @staticmethod
    def resolve_first_seen(obj):
        return obj.first_seen.date()

    @staticmethod
    def resolve_last_seen(obj):
        return obj.last_seen.date()


class PropertyListOut(Schema):
    kind: str
    kind_label: str
    properties: List[PropertyRowOut]
    page: int
    num_pages: int
    total_count: int
    has_next: bool
    has_previous: bool
    districts: List[str]
    selected_district: str
    selected_street: str


class LinkedAdOut(Schema):
    """One row of the property-detail linked-ads table — built from
    both the rent and sale ad models (all_objects via linked_ads)."""
    ad_id: str
    link: str
    deal: str
    price: Optional[float]
    price_suffix: str
    match_status: str
    match_score: Optional[float]
    first_seen: date
    last_seen: date
    days_active: int


class PropertyDetailOut(Schema):
    id: int
    kind: str
    kind_label: str
    district: str
    street_name: str
    street_no: str
    apartment_no: Optional[str]
    region_name: Optional[str]
    rooms: int
    size: float
    floor: Optional[int]
    max_floor: Optional[int]
    floors: Optional[int]
    land_area_sqm: Optional[float]
    days_on_market: int
    first_seen: date
    last_seen: date
    ad_rows: List[LinkedAdOut]


# --- Helpers (moved verbatim from the retired views.py) ---


def _region_and_descendant_ids(region):
    ids = [region.id]
    for child in region.sub_regions.all():
        ids.extend(_region_and_descendant_ids(child))
    return ids


def _linked_property_stats(ads_qs, sighting_models):
    """Per-property stats for ads with a confirmed property link.

    Returns (distinct linked property count, avg days-on-market)
    where days-on-market is the union of sighting dates across all
    ads linked to each property (both deal types, and including ads
    outside the report window — the metric survives delete+repost).
    """
    prop_ids = (
        ads_qs.filter(
            property__isnull=False,
            property_match_status__in=('auto', 'manual'),
        )
        .values_list('property', flat=True)
        .distinct()
    )
    seen_by_prop = defaultdict(set)
    for sighting_model in sighting_models:
        pairs = (
            sighting_model.objects
            .filter(ad__property__in=prop_ids)
            .values_list('ad__property', 'seen_on')
        )
        for prop_id, seen_on in pairs:
            seen_by_prop[prop_id].add(seen_on)
    total_properties = len(prop_ids)
    days = [len(dates) for dates in seen_by_prop.values()]
    avg_days = sum(days) / len(days) if days else None
    return total_properties, avg_days


def _distinct_linked_property_count(*ads_querysets):
    prop_ids = set()
    for ads_qs in ads_querysets:
        prop_ids.update(
            ads_qs.filter(
                property__isnull=False,
                property_match_status__in=('auto', 'manual'),
            ).values_list('property', flat=True)
        )
    return len(prop_ids)


def _default_date_range(date_from, date_to):
    today = date.today()
    if date_from is None:
        date_from = today - timedelta(days=STATS_DEFAULT_DAYS)
    if date_to is None:
        date_to = today
    return date_from, date_to


def _compute_apartment_region_stats(
    region, date_from, date_to, deal_type=''
):
    region_ids = _region_and_descendant_ids(region)

    if deal_type == 'RENT':
        ads_qs = ApartmentForRent.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        ).annotate(sighting_count=Count('sightings', distinct=True))
        price_field = 'monthly_price_per_sqm'
    elif deal_type == 'SELL':
        ads_qs = ApartmentForSale.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        ).annotate(sighting_count=Count('sightings', distinct=True))
        price_field = 'price_per_sqm'
    else:
        rent_qs = ApartmentForRent.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        )
        sale_qs = ApartmentForSale.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        )
        total_ads = rent_qs.count() + sale_qs.count()
        stats = {
            'total_ads': total_ads,
            'total_properties': _distinct_linked_property_count(
                rent_qs, sale_qs
            ),
            'avg_price_per_sqm': None,
            'avg_size': None,
            'avg_days_tracked': None,
            'avg_days_on_market': None,
            'region': region,
        }
        return stats

    stats = ads_qs.aggregate(
        total_ads=Count('id', distinct=True),
        avg_price_per_sqm=Avg(price_field),
        avg_size=Avg('size'),
        avg_days_tracked=Avg('sighting_count'),
    )
    stats['total_properties'], stats['avg_days_on_market'] = (
        _linked_property_stats(
            ads_qs,
            (ApartmentForRentSighting, ApartmentForSaleSighting),
        )
    )
    stats['region'] = region
    return stats


def _compute_house_region_stats(
    region, date_from, date_to, deal_type=''
):
    region_ids = _region_and_descendant_ids(region)

    if deal_type == 'RENT':
        ads_qs = HouseForRent.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        ).annotate(sighting_count=Count('sightings', distinct=True))
        price_field = 'monthly_price_per_sqm'
    elif deal_type == 'SELL':
        ads_qs = HouseForSale.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        ).annotate(sighting_count=Count('sightings', distinct=True))
        price_field = 'price_per_sqm'
    else:
        rent_qs = HouseForRent.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        )
        sale_qs = HouseForSale.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        )
        total_ads = rent_qs.count() + sale_qs.count()
        stats = {
            'total_ads': total_ads,
            'total_properties': _distinct_linked_property_count(
                rent_qs, sale_qs
            ),
            'avg_price_per_sqm': None,
            'avg_size': None,
            'avg_days_tracked': None,
            'avg_days_on_market': None,
            'region': region,
        }
        return stats

    stats = ads_qs.aggregate(
        total_ads=Count('id', distinct=True),
        avg_price_per_sqm=Avg(price_field),
        avg_size=Avg('size'),
        avg_days_tracked=Avg('sighting_count'),
    )
    stats['total_properties'], stats['avg_days_on_market'] = (
        _linked_property_stats(
            ads_qs,
            (HouseForRentSighting, HouseForSaleSighting),
        )
    )
    stats['region'] = region
    return stats


def _compute_region_stats(kind):
    if kind == 'apartment':
        return _compute_apartment_region_stats
    return _compute_house_region_stats


# --- Ops ---


@router.get('/ads/', auth=None, response=AdsTableOut)
def ads_table(
    request,
    kind: Kind,
    deal: Deal,
    district: str = Query('', max_length=255),
    rooms: Optional[int] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    page: int = 1,
):
    """Ads table page — mirrors the four retired *_ads_table views.
    Rent tables filter on monthly_price_per_sqm, sale tables on
    price_per_sqm (the template's '€/m² min/max' inputs)."""
    model = ADS_TABLE_MODELS[(kind, deal)]
    qs = model.objects.all().order_by('-post_date')

    districts = (
        model.objects.values_list('district', flat=True)
        .distinct()
        .order_by('district')
    )
    room_choices = (
        model.objects.values_list('rooms', flat=True)
        .distinct()
        .order_by('rooms')
    )

    if district:
        qs = qs.filter(district=district)
    if rooms is not None:
        qs = qs.filter(rooms=rooms)
    price_field = (
        'monthly_price_per_sqm' if deal == 'rent' else 'price_per_sqm'
    )
    if price_min is not None:
        qs = qs.filter(**{f'{price_field}__gte': price_min})
    if price_max is not None:
        qs = qs.filter(**{f'{price_field}__lte': price_max})

    # The template called ad.days_active (a sightings.count() per row);
    # the annotation is the same count without the N+1.
    qs = qs.annotate(days_active_count=Count('sightings', distinct=True))
    if kind == 'apartment':
        qs = qs.select_related('project')

    paginator = Paginator(qs, ADS_PER_PAGE)
    ads = paginator.get_page(page)

    return AdsTableOut(
        ads=list(ads.object_list),
        page=ads.number,
        num_pages=paginator.num_pages,
        total_count=paginator.count,
        has_next=ads.has_next(),
        has_previous=ads.has_previous(),
        districts=list(districts),
        room_choices=list(room_choices),
        filters=AdsFiltersOut(
            district=district,
            rooms=rooms,
            price_min=price_min,
            price_max=price_max,
        ),
    )


@router.get(
    '/regions/config/', auth=None, response=RegionConfigOut
)
def region_config(request, kind: Kind):
    """Region-config page read — mirrors the GET half of the retired
    apartment/house_region_config views. The house set is keyed off
    the '/homes-summer-residences/' URL substring, not the category
    column — identical to the old views."""
    if kind == 'apartment':
        parents = (
            Region.objects
            .filter(parent__isnull=True)
            .exclude(url__contains=HOUSE_REGION_URL)
            .prefetch_related('sub_regions')
            .order_by('name')
        )
        total_count = Region.objects.exclude(
            url__contains=HOUSE_REGION_URL
        ).count()
        enabled_count = Region.objects.filter(
            scrape_enabled=True
        ).exclude(url__contains=HOUSE_REGION_URL).count()
    else:
        parents = (
            Region.objects
            .filter(
                parent__isnull=True,
                url__contains=HOUSE_REGION_URL,
            )
            .prefetch_related('sub_regions')
            .order_by('name')
        )
        total_count = Region.objects.filter(
            url__contains=HOUSE_REGION_URL
        ).count()
        enabled_count = Region.objects.filter(
            scrape_enabled=True,
            url__contains=HOUSE_REGION_URL,
        ).count()

    return RegionConfigOut(
        kind=kind,
        regions_tree=list(parents),
        enabled_count=enabled_count,
        total_count=total_count,
    )


@router.post('/regions/config/', response=RegionConfigSavedOut)
def save_region_config(request, payload: RegionConfigIn):
    """Save checked regions — session-auth replacement for the two
    retired config POST forms. Same semantics as the views: the kind's
    region set is first disabled wholesale, then every submitted URL
    is re-enabled (a submitted URL outside the kind's set is enabled
    too — verbatim from the old form handler)."""
    if payload.kind == 'apartment':
        Region.objects.exclude(
            url__contains=HOUSE_REGION_URL
        ).update(scrape_enabled=False)
    else:
        Region.objects.filter(
            url__contains=HOUSE_REGION_URL
        ).update(scrape_enabled=False)

    if payload.regions:
        Region.objects.filter(url__in=payload.regions).update(
            scrape_enabled=True
        )
    return RegionConfigSavedOut(
        success=True,
        message='Region configuration saved.',
    )


@router.get('/regions/stats/', auth=None, response=RegionStatsOut)
def region_stats(
    request,
    kind: Kind,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    deal_type: str = Query('', max_length=10),
    regions: List[int] = Query([]),
):
    """Region stats page — mirrors apartment/house_region_stats.
    `regions` repeats per checked parent region; results stay null
    until at least one is selected."""
    date_from, date_to = _default_date_range(date_from, date_to)
    category = 'APARTMENT' if kind == 'apartment' else 'HOUSE'
    parent_regions = (
        Region.objects
        .filter(parent__isnull=True, category=category)
        .order_by('name')
    )

    compute = _compute_region_stats(kind)
    results = None
    if regions:
        selected_regions = parent_regions.filter(id__in=regions)
        results = [
            compute(region, date_from, date_to, deal_type)
            for region in selected_regions
        ]

    return RegionStatsOut(
        kind=kind,
        parent_regions=list(parent_regions),
        selected_ids=list(regions),
        date_from=date_from,
        date_to=date_to,
        deal_type=deal_type,
        results=results,
    )


@router.get(
    '/regions/{region_id}/children/',
    auth=None,
    response=RegionStatsChildrenOut,
)
def region_stats_children(
    request,
    region_id: int,
    kind: Kind,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    deal_type: str = Query('', max_length=10),
):
    """Sub-region stats for one parent — mirrors the retired
    *_region_stats_children views (404 unless the region is a
    parent)."""
    parent_region = get_object_or_404(
        Region, pk=region_id, parent__isnull=True
    )
    date_from, date_to = _default_date_range(date_from, date_to)

    compute = _compute_region_stats(kind)
    children = parent_region.sub_regions.order_by('name')
    results = [
        compute(child, date_from, date_to, deal_type)
        for child in children
    ]

    return RegionStatsChildrenOut(
        kind=kind,
        parent_region=parent_region,
        date_from=date_from,
        date_to=date_to,
        deal_type=deal_type,
        results=results,
    )


@router.get(
    '/regions/{region_id}/ads/', auth=None, response=RegionAdsOut
)
def region_ads_list(
    request,
    region_id: int,
    kind: Kind,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    deal_type: str = Query('', max_length=10),
    page: int = 1,
):
    """Ads in a region subtree — mirrors the retired *_region_ads_list
    views: the subtree filter is first_seen inside the window, and a
    missing/blank deal_type yields an empty table."""
    region = get_object_or_404(Region, pk=region_id)
    date_from, date_to = _default_date_range(date_from, date_to)

    region_ids = _region_and_descendant_ids(region)
    rent_model = (
        ApartmentForRent if kind == 'apartment' else HouseForRent
    )
    sale_model = (
        ApartmentForSale if kind == 'apartment' else HouseForSale
    )

    if deal_type == 'RENT':
        ads_qs = rent_model.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        ).order_by('-first_seen')
    elif deal_type == 'SELL':
        ads_qs = sale_model.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        ).order_by('-first_seen')
    else:
        ads_qs = rent_model.objects.none()

    ads_qs = ads_qs.annotate(
        days_active_count=Count('sightings', distinct=True)
    )

    paginator = Paginator(ads_qs, ADS_PER_PAGE)
    ads = paginator.get_page(page)

    return RegionAdsOut(
        kind=kind,
        region=region,
        ads=list(ads.object_list),
        page=ads.number,
        num_pages=paginator.num_pages,
        total_count=paginator.count,
        has_next=ads.has_next(),
        has_previous=ads.has_previous(),
        date_from=date_from,
        date_to=date_to,
        deal_type=deal_type,
    )


@router.get(
    '/sightings/', auth=None, response=DailySightingsOut
)
def daily_sightings(
    request,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    order: str = Query('desc', max_length=10),
    region: Optional[int] = None,
):
    """Daily sightings report — mirrors the retired
    daily_sightings_report view: per-day sighting counts for each of
    the four ad tables, optionally restricted to a region subtree."""
    date_from, date_to = _default_date_range(date_from, date_to)
    if order not in ('asc', 'desc'):
        order = 'desc'

    apartment_rent_qs = ApartmentForRentSighting.objects.filter(
        seen_on__gte=date_from, seen_on__lte=date_to
    )
    apartment_sale_qs = ApartmentForSaleSighting.objects.filter(
        seen_on__gte=date_from, seen_on__lte=date_to
    )
    house_rent_qs = HouseForRentSighting.objects.filter(
        seen_on__gte=date_from, seen_on__lte=date_to
    )
    house_sale_qs = HouseForSaleSighting.objects.filter(
        seen_on__gte=date_from, seen_on__lte=date_to
    )

    if region is not None:
        selected_region = get_object_or_404(Region, pk=region)
        region_ids = _region_and_descendant_ids(selected_region)
        apartment_rent_qs = apartment_rent_qs.filter(
            ad__region_id__in=region_ids
        )
        apartment_sale_qs = apartment_sale_qs.filter(
            ad__region_id__in=region_ids
        )
        house_rent_qs = house_rent_qs.filter(
            ad__region_id__in=region_ids
        )
        house_sale_qs = house_sale_qs.filter(
            ad__region_id__in=region_ids
        )

    def counts_by_date(qs):
        return {
            item['seen_on']: item['count']
            for item in qs.values('seen_on')
            .annotate(count=Count('id'))
            .order_by('seen_on')
        }

    apartment_rent_by_date = counts_by_date(apartment_rent_qs)
    apartment_sale_by_date = counts_by_date(apartment_sale_qs)
    house_rent_by_date = counts_by_date(house_rent_qs)
    house_sale_by_date = counts_by_date(house_sale_qs)

    all_dates = set()
    all_dates.update(apartment_rent_by_date.keys())
    all_dates.update(apartment_sale_by_date.keys())
    all_dates.update(house_rent_by_date.keys())
    all_dates.update(house_sale_by_date.keys())

    daily_data = []
    sorted_dates = sorted(all_dates, reverse=(order == 'desc'))
    for current_date in sorted_dates:
        apt_rent = apartment_rent_by_date.get(current_date, 0)
        apt_sale = apartment_sale_by_date.get(current_date, 0)
        house_rent = house_rent_by_date.get(current_date, 0)
        house_sale = house_sale_by_date.get(current_date, 0)

        daily_data.append({
            'date': current_date,
            'apartment_rent': apt_rent,
            'apartment_sale': apt_sale,
            'apartment_total': apt_rent + apt_sale,
            'house_rent': house_rent,
            'house_sale': house_sale,
            'house_total': house_rent + house_sale,
            'grand_total': (
                apt_rent + apt_sale + house_rent + house_sale
            ),
        })

    regions = (
        Region.objects
        .filter(parent__isnull=True)
        .prefetch_related('sub_regions')
        .order_by('name')
    )

    return DailySightingsOut(
        date_from=date_from,
        date_to=date_to,
        order=order,
        selected_region=region,
        daily_data=daily_data,
        regions=list(regions),
    )


@router.get('/properties/', auth=None, response=PropertyListOut)
def property_list(
    request,
    kind: Kind,
    district: str = Query('', max_length=255),
    street: str = Query('', max_length=255),
    page: int = 1,
):
    """Property list — mirrors the retired property_list view:
    properties with their linked-ad counts, district/street filters."""
    model, label = PROPERTY_MODELS[kind]

    qs = model.objects.annotate(
        rent_ad_count=Count('rent_ads', distinct=True),
        sale_ad_count=Count('sale_ads', distinct=True),
    ).order_by('-last_seen')

    if district:
        qs = qs.filter(district=district)
    if street:
        qs = qs.filter(street_name__icontains=street)

    districts = (
        model.objects.values_list('district', flat=True)
        .distinct()
        .order_by('district')
    )

    paginator = Paginator(qs, PROPERTIES_PER_PAGE)
    properties = paginator.get_page(page)

    return PropertyListOut(
        kind=kind,
        kind_label=label,
        properties=list(properties.object_list),
        page=properties.number,
        num_pages=paginator.num_pages,
        total_count=paginator.count,
        has_next=properties.has_next(),
        has_previous=properties.has_previous(),
        districts=list(districts),
        selected_district=district,
        selected_street=street,
    )


@router.get(
    '/properties/{kind}/{pk}/',
    auth=None,
    response=PropertyDetailOut,
)
def property_detail(request, kind: str, pk: int):
    """Property detail — mirrors the retired property_detail view,
    including linked_ads() (all_objects: hidden and misclassified ads
    still belong to the property) and the days_on_market union count."""
    model_tuple = PROPERTY_MODELS.get(kind)
    if model_tuple is None:
        raise ApiHttpError(400, 'unknown kind', code='unknown_kind')
    model, label = model_tuple
    prop = get_object_or_404(model, pk=pk)

    ad_rows = []
    ads = sorted(
        prop.linked_ads(), key=lambda a: (a.first_seen, a.id)
    )
    for ad in ads:
        is_rent = hasattr(ad, 'monthly_price')
        ad_rows.append(LinkedAdOut(
            ad_id=ad.ad_id,
            link=ad.link,
            deal='Rent' if is_rent else 'Sale',
            price=ad.monthly_price if is_rent else ad.total_price,
            price_suffix='/mo' if is_rent else '',
            match_status=_MATCH_STATUS_LABELS.get(
                ad.property_match_status, ad.property_match_status
            ),
            match_score=ad.property_match_score,
            first_seen=ad.first_seen.date(),
            last_seen=ad.last_seen.date(),
            days_active=ad.days_active,
        ))

    return PropertyDetailOut(
        id=prop.pk,
        kind=kind,
        kind_label=label,
        district=prop.district,
        street_name=prop.street_name,
        street_no=prop.street_no,
        apartment_no=getattr(prop, 'apartment_no', '') or '',
        region_name=prop.region.name if prop.region else None,
        rooms=prop.rooms,
        size=prop.size,
        floor=getattr(prop, 'floor', None),
        max_floor=getattr(prop, 'max_floor', None),
        floors=getattr(prop, 'floors', None),
        land_area_sqm=getattr(prop, 'land_area_sqm', None),
        days_on_market=prop.days_on_market,
        first_seen=prop.first_seen.date(),
        last_seen=prop.last_seen.date(),
        ad_rows=ad_rows,
    )

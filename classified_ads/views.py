from datetime import date, timedelta

from django.core.paginator import Paginator
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, render, redirect

from .models import ClassifiedAd, Region

STATS_DEFAULT_DAYS = 30


def index(request):
    return render(request, 'classified_ads/index.html')


def ads_table(request):
    qs = ClassifiedAd.objects.all().order_by('-post_date')

    districts = (
        ClassifiedAd.objects.values_list('district', flat=True)
        .distinct()
        .order_by('district')
    )
    room_choices = (
        ClassifiedAd.objects.values_list('rooms', flat=True)
        .distinct()
        .order_by('rooms')
    )

    district = request.GET.get('district', '').strip()
    rooms = request.GET.get('rooms', '').strip()
    price_min = request.GET.get('price_min', '').strip()
    price_max = request.GET.get('price_max', '').strip()
    deal_type = request.GET.get('deal_type', '').strip()

    if district:
        qs = qs.filter(district=district)
    if rooms:
        qs = qs.filter(rooms=rooms)
    if price_min:
        qs = qs.filter(price_per_sqm__gte=price_min)
    if price_max:
        qs = qs.filter(price_per_sqm__lte=price_max)
    if deal_type:
        qs = qs.filter(deal_type=deal_type)

    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page')
    ads = paginator.get_page(page_number)

    return render(request, 'classified_ads/ads_table.html', {
        'ads': ads,
        'districts': districts,
        'room_choices': room_choices,
        'deal_type_choices': ClassifiedAd.DEAL_TYPE_CHOICES,
        'selected_district': district,
        'selected_rooms': rooms,
        'selected_price_min': price_min,
        'selected_price_max': price_max,
        'selected_deal_type': deal_type,
        'total_count': qs.count(),
    })


def region_config(request):
    if request.method == 'POST':
        checked_urls = set(request.POST.getlist('regions'))
        Region.objects.all().update(scrape_enabled=False)

        if checked_urls:
            Region.objects.filter(url__in=checked_urls).update(scrape_enabled=True)
        return redirect('classified_ads:region_config')

    regions = (
        Region.objects
        .filter(parent__isnull=True)
        .prefetch_related('sub_regions')
        .order_by('name')
    )
    total_count = Region.objects.count()
    enabled_count = Region.objects.filter(scrape_enabled=True).count()

    return render(request, 'classified_ads/region_config.html', {
        'regions_tree': regions,
        'enabled_count': enabled_count,
        'total_count': total_count,
    })


def _parse_date_range(request):
    default_from = date.today() - timedelta(days=STATS_DEFAULT_DAYS)
    default_to = date.today()

    date_from = request.GET.get('date_from', '').strip() or default_from.isoformat()
    date_to = request.GET.get('date_to', '').strip() or default_to.isoformat()
    return date_from, date_to


def _region_and_descendant_ids(region):
    ids = [region.id]
    for child in region.sub_regions.all():
        ids.extend(_region_and_descendant_ids(child))
    return ids


def _compute_region_stats(region, date_from, date_to, deal_type=''):
    region_ids = _region_and_descendant_ids(region)
    ads_qs = ClassifiedAd.objects.filter(
        region_id__in=region_ids,
        first_seen__date__gte=date_from,
        first_seen__date__lte=date_to,
    ).annotate(sighting_count=Count('sightings', distinct=True))

    if deal_type:
        ads_qs = ads_qs.filter(deal_type=deal_type)

    stats = ads_qs.aggregate(
        total_ads=Count('id', distinct=True),
        avg_price_per_sqm=Avg('price_per_sqm'),
        avg_size=Avg('size'),
        avg_days_tracked=Avg('sighting_count'),
    )
    stats['region'] = region
    return stats


def region_stats(request):
    date_from, date_to = _parse_date_range(request)
    deal_type = request.GET.get('deal_type', '').strip()

    parent_regions = Region.objects.filter(parent__isnull=True).order_by('name')
    selected_ids = set(request.GET.getlist('regions'))

    results = None
    if selected_ids:
        selected_regions = parent_regions.filter(id__in=selected_ids)
        results = [
            _compute_region_stats(region, date_from, date_to, deal_type)
            for region in selected_regions
        ]

    return render(request, 'classified_ads/region_stats.html', {
        'parent_regions': parent_regions,
        'selected_ids': selected_ids,
        'date_from': date_from,
        'date_to': date_to,
        'deal_type': deal_type,
        'deal_type_choices': ClassifiedAd.DEAL_TYPE_CHOICES,
        'results': results,
    })


def region_stats_children(request, region_id):
    parent_region = get_object_or_404(Region, pk=region_id, parent__isnull=True)
    date_from, date_to = _parse_date_range(request)
    deal_type = request.GET.get('deal_type', '').strip()

    children = parent_region.sub_regions.order_by('name')
    results = [
        _compute_region_stats(child, date_from, date_to, deal_type)
        for child in children
    ]

    return render(request, 'classified_ads/region_stats_children.html', {
        'parent_region': parent_region,
        'results': results,
        'date_from': date_from,
        'date_to': date_to,
        'deal_type': deal_type,
        'deal_type_choices': ClassifiedAd.DEAL_TYPE_CHOICES,
    })


def region_ads_list(request, region_id):
    region = get_object_or_404(Region, pk=region_id)
    date_from, date_to = _parse_date_range(request)
    deal_type = request.GET.get('deal_type', '').strip()

    region_ids = _region_and_descendant_ids(region)
    ads_qs = ClassifiedAd.objects.filter(
        region_id__in=region_ids,
        first_seen__date__gte=date_from,
        first_seen__date__lte=date_to,
    ).order_by('-first_seen')

    if deal_type:
        ads_qs = ads_qs.filter(deal_type=deal_type)

    paginator = Paginator(ads_qs, 50)
    page_number = request.GET.get('page')
    ads = paginator.get_page(page_number)

    return render(request, 'classified_ads/region_ads_list.html', {
        'region': region,
        'ads': ads,
        'date_from': date_from,
        'date_to': date_to,
        'deal_type': deal_type,
        'deal_type_choices': ClassifiedAd.DEAL_TYPE_CHOICES,
        'total_count': ads_qs.count(),
    })

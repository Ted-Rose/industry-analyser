from datetime import date, timedelta

from django.core.paginator import Paginator
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, render, redirect

from .models import (
    ApartmentForRent,
    ApartmentForSale,
    ApartmentForRentSighting,
    ApartmentForSaleSighting,
    HouseForRent,
    HouseForSale,
    HouseForRentSighting,
    HouseForSaleSighting,
    Region,
)

STATS_DEFAULT_DAYS = 30


def index(request):
    return render(request, 'classified_ads/index.html')


def apartment_ads_table(request):
    return redirect('classified_ads:apartment_rent_ads_table')


def apartment_rent_ads_table(request):
    qs = ApartmentForRent.objects.all().order_by('-post_date')

    districts = (
        ApartmentForRent.objects.values_list('district', flat=True)
        .distinct()
        .order_by('district')
    )
    room_choices = (
        ApartmentForRent.objects.values_list('rooms', flat=True)
        .distinct()
        .order_by('rooms')
    )

    district = request.GET.get('district', '').strip()
    rooms = request.GET.get('rooms', '').strip()
    price_min = request.GET.get('price_min', '').strip()
    price_max = request.GET.get('price_max', '').strip()

    if district:
        qs = qs.filter(district=district)
    if rooms:
        qs = qs.filter(rooms=rooms)
    if price_min:
        qs = qs.filter(monthly_price_per_sqm__gte=price_min)
    if price_max:
        qs = qs.filter(monthly_price_per_sqm__lte=price_max)

    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page')
    ads = paginator.get_page(page_number)

    return render(
        request,
        'classified_ads/apartment_rent_ads_table.html',
        {
            'ads': ads,
            'districts': districts,
            'room_choices': room_choices,
            'selected_district': district,
            'selected_rooms': rooms,
            'selected_price_min': price_min,
            'selected_price_max': price_max,
            'total_count': qs.count(),
            'ad_type': 'rent',
        }
    )


def apartment_sale_ads_table(request):
    qs = ApartmentForSale.objects.all().order_by('-post_date')

    districts = (
        ApartmentForSale.objects.values_list('district', flat=True)
        .distinct()
        .order_by('district')
    )
    room_choices = (
        ApartmentForSale.objects.values_list('rooms', flat=True)
        .distinct()
        .order_by('rooms')
    )

    district = request.GET.get('district', '').strip()
    rooms = request.GET.get('rooms', '').strip()
    price_min = request.GET.get('price_min', '').strip()
    price_max = request.GET.get('price_max', '').strip()

    if district:
        qs = qs.filter(district=district)
    if rooms:
        qs = qs.filter(rooms=rooms)
    if price_min:
        qs = qs.filter(price_per_sqm__gte=price_min)
    if price_max:
        qs = qs.filter(price_per_sqm__lte=price_max)

    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page')
    ads = paginator.get_page(page_number)

    return render(
        request,
        'classified_ads/apartment_sale_ads_table.html',
        {
            'ads': ads,
            'districts': districts,
            'room_choices': room_choices,
            'selected_district': district,
            'selected_rooms': rooms,
            'selected_price_min': price_min,
            'selected_price_max': price_max,
            'total_count': qs.count(),
            'ad_type': 'sale',
        }
    )


def apartment_region_config(request):
    if request.method == 'POST':
        checked_urls = set(request.POST.getlist('regions'))
        apartment_regions = Region.objects.exclude(
            url__contains='/homes-summer-residences/'
        )
        apartment_regions.update(scrape_enabled=False)

        if checked_urls:
            Region.objects.filter(url__in=checked_urls).update(
                scrape_enabled=True
            )
        return redirect('classified_ads:apartment_region_config')

    regions = (
        Region.objects
        .filter(parent__isnull=True)
        .exclude(url__contains='/homes-summer-residences/')
        .prefetch_related('sub_regions')
        .order_by('name')
    )
    total_count = Region.objects.exclude(
        url__contains='/homes-summer-residences/'
    ).count()
    enabled_count = Region.objects.filter(
        scrape_enabled=True
    ).exclude(url__contains='/homes-summer-residences/').count()

    return render(
        request,
        'classified_ads/apartment_region_config.html',
        {
            'regions_tree': regions,
            'enabled_count': enabled_count,
            'total_count': total_count,
        }
    )


def house_region_config(request):
    if request.method == 'POST':
        checked_urls = set(request.POST.getlist('regions'))
        house_regions = Region.objects.filter(
            url__contains='/homes-summer-residences/'
        )
        house_regions.update(scrape_enabled=False)

        if checked_urls:
            Region.objects.filter(url__in=checked_urls).update(
                scrape_enabled=True
            )
        return redirect('classified_ads:house_region_config')

    regions = (
        Region.objects
        .filter(parent__isnull=True, url__contains='/homes-summer-residences/')
        .prefetch_related('sub_regions')
        .order_by('name')
    )
    total_count = Region.objects.filter(
        url__contains='/homes-summer-residences/'
    ).count()
    enabled_count = Region.objects.filter(
        scrape_enabled=True, url__contains='/homes-summer-residences/'
    ).count()

    return render(
        request,
        'classified_ads/house_region_config.html',
        {
            'regions_tree': regions,
            'enabled_count': enabled_count,
            'total_count': total_count,
        }
    )


def _parse_date_range(request):
    default_from = date.today() - timedelta(days=STATS_DEFAULT_DAYS)
    default_to = date.today()

    date_from = (
        request.GET.get('date_from', '').strip()
        or default_from.isoformat()
    )
    date_to = (
        request.GET.get('date_to', '').strip()
        or default_to.isoformat()
    )
    return date_from, date_to


def _region_and_descendant_ids(region):
    ids = [region.id]
    for child in region.sub_regions.all():
        ids.extend(_region_and_descendant_ids(child))
    return ids


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
            'avg_price_per_sqm': None,
            'avg_size': None,
            'avg_days_tracked': None,
            'region': region,
        }
        return stats

    stats = ads_qs.aggregate(
        total_ads=Count('id', distinct=True),
        avg_price_per_sqm=Avg(price_field),
        avg_size=Avg('size'),
        avg_days_tracked=Avg('sighting_count'),
    )
    stats['region'] = region
    return stats


def apartment_region_stats(request):
    date_from, date_to = _parse_date_range(request)
    deal_type = request.GET.get('deal_type', '').strip()

    parent_regions = (
        Region.objects.filter(parent__isnull=True).order_by('name')
    )
    selected_ids = set(request.GET.getlist('regions'))

    results = None
    if selected_ids:
        selected_regions = parent_regions.filter(id__in=selected_ids)
        results = [
            _compute_apartment_region_stats(
                region, date_from, date_to, deal_type
            )
            for region in selected_regions
        ]

    deal_type_choices = [('RENT', 'Rent'), ('SELL', 'Sell')]

    return render(
        request,
        'classified_ads/region_stats.html',
        {
            'parent_regions': parent_regions,
            'selected_ids': selected_ids,
            'date_from': date_from,
            'date_to': date_to,
            'deal_type': deal_type,
            'deal_type_choices': deal_type_choices,
            'results': results,
        }
    )


def apartment_region_stats_children(request, region_id):
    parent_region = get_object_or_404(
        Region, pk=region_id, parent__isnull=True
    )
    date_from, date_to = _parse_date_range(request)
    deal_type = request.GET.get('deal_type', '').strip()

    children = parent_region.sub_regions.order_by('name')
    results = [
        _compute_apartment_region_stats(
            child, date_from, date_to, deal_type
        )
        for child in children
    ]

    deal_type_choices = [('RENT', 'Rent'), ('SELL', 'Sell')]

    return render(
        request,
        'classified_ads/region_stats_children.html',
        {
            'parent_region': parent_region,
            'results': results,
            'date_from': date_from,
            'date_to': date_to,
            'deal_type': deal_type,
            'deal_type_choices': deal_type_choices,
        }
    )


def apartment_region_ads_list(request, region_id):
    region = get_object_or_404(Region, pk=region_id)
    date_from, date_to = _parse_date_range(request)
    deal_type = request.GET.get('deal_type', '').strip()

    region_ids = _region_and_descendant_ids(region)

    if deal_type == 'RENT':
        ads_qs = ApartmentForRent.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        ).order_by('-first_seen')
    elif deal_type == 'SELL':
        ads_qs = ApartmentForSale.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        ).order_by('-first_seen')
    else:
        ads_qs = ApartmentForRent.objects.none()

    paginator = Paginator(ads_qs, 50)
    page_number = request.GET.get('page')
    ads = paginator.get_page(page_number)

    deal_type_choices = [('RENT', 'Rent'), ('SELL', 'Sell')]

    return render(request, 'classified_ads/region_ads_list.html', {
        'region': region,
        'ads': ads,
        'date_from': date_from,
        'date_to': date_to,
        'deal_type': deal_type,
        'deal_type_choices': deal_type_choices,
        'total_count': ads_qs.count(),
    })


def house_ads_table(request):
    return redirect('classified_ads:house_rent_ads_table')


def house_rent_ads_table(request):
    qs = HouseForRent.objects.all().order_by('-post_date')

    districts = (
        HouseForRent.objects.values_list('district', flat=True)
        .distinct()
        .order_by('district')
    )
    room_choices = (
        HouseForRent.objects.values_list('rooms', flat=True)
        .distinct()
        .order_by('rooms')
    )

    district = request.GET.get('district', '').strip()
    rooms = request.GET.get('rooms', '').strip()
    price_min = request.GET.get('price_min', '').strip()
    price_max = request.GET.get('price_max', '').strip()

    if district:
        qs = qs.filter(district=district)
    if rooms:
        qs = qs.filter(rooms=rooms)
    if price_min:
        qs = qs.filter(monthly_price_per_sqm__gte=price_min)
    if price_max:
        qs = qs.filter(monthly_price_per_sqm__lte=price_max)

    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page')
    ads = paginator.get_page(page_number)

    return render(
        request,
        'classified_ads/house_rent_ads_table.html',
        {
            'ads': ads,
            'districts': districts,
            'room_choices': room_choices,
            'selected_district': district,
            'selected_rooms': rooms,
            'selected_price_min': price_min,
            'selected_price_max': price_max,
            'total_count': qs.count(),
            'ad_type': 'rent',
        }
    )


def house_sale_ads_table(request):
    qs = HouseForSale.objects.all().order_by('-post_date')

    districts = (
        HouseForSale.objects.values_list('district', flat=True)
        .distinct()
        .order_by('district')
    )
    room_choices = (
        HouseForSale.objects.values_list('rooms', flat=True)
        .distinct()
        .order_by('rooms')
    )

    district = request.GET.get('district', '').strip()
    rooms = request.GET.get('rooms', '').strip()
    price_min = request.GET.get('price_min', '').strip()
    price_max = request.GET.get('price_max', '').strip()

    if district:
        qs = qs.filter(district=district)
    if rooms:
        qs = qs.filter(rooms=rooms)
    if price_min:
        qs = qs.filter(price_per_sqm__gte=price_min)
    if price_max:
        qs = qs.filter(price_per_sqm__lte=price_max)

    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page')
    ads = paginator.get_page(page_number)

    return render(
        request,
        'classified_ads/house_sale_ads_table.html',
        {
            'ads': ads,
            'districts': districts,
            'room_choices': room_choices,
            'selected_district': district,
            'selected_rooms': rooms,
            'selected_price_min': price_min,
            'selected_price_max': price_max,
            'total_count': qs.count(),
            'ad_type': 'sale',
        }
    )


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
            'avg_price_per_sqm': None,
            'avg_size': None,
            'avg_days_tracked': None,
            'region': region,
        }
        return stats

    stats = ads_qs.aggregate(
        total_ads=Count('id', distinct=True),
        avg_price_per_sqm=Avg(price_field),
        avg_size=Avg('size'),
        avg_days_tracked=Avg('sighting_count'),
    )
    stats['region'] = region
    return stats


def house_region_stats(request):
    date_from, date_to = _parse_date_range(request)
    deal_type = request.GET.get('deal_type', '').strip()

    parent_regions = (
        Region.objects
        .filter(parent__isnull=True, url__contains='/homes-summer-residences/')
        .order_by('name')
    )
    selected_ids = set(request.GET.getlist('regions'))

    results = None
    if selected_ids:
        selected_regions = parent_regions.filter(id__in=selected_ids)
        results = [
            _compute_house_region_stats(
                region, date_from, date_to, deal_type
            )
            for region in selected_regions
        ]

    deal_type_choices = [('RENT', 'Rent'), ('SELL', 'Sell')]

    return render(
        request,
        'classified_ads/house_region_stats.html',
        {
            'parent_regions': parent_regions,
            'selected_ids': selected_ids,
            'date_from': date_from,
            'date_to': date_to,
            'deal_type': deal_type,
            'deal_type_choices': deal_type_choices,
            'results': results,
        }
    )


def house_region_stats_children(request, region_id):
    parent_region = get_object_or_404(
        Region, pk=region_id, parent__isnull=True
    )
    date_from, date_to = _parse_date_range(request)
    deal_type = request.GET.get('deal_type', '').strip()

    children = parent_region.sub_regions.order_by('name')
    results = [
        _compute_house_region_stats(
            child, date_from, date_to, deal_type
        )
        for child in children
    ]

    deal_type_choices = [('RENT', 'Rent'), ('SELL', 'Sell')]

    return render(
        request,
        'classified_ads/house_region_stats_children.html',
        {
            'parent_region': parent_region,
            'results': results,
            'date_from': date_from,
            'date_to': date_to,
            'deal_type': deal_type,
            'deal_type_choices': deal_type_choices,
        }
    )


def house_region_ads_list(request, region_id):
    region = get_object_or_404(Region, pk=region_id)
    date_from, date_to = _parse_date_range(request)
    deal_type = request.GET.get('deal_type', '').strip()

    region_ids = _region_and_descendant_ids(region)

    if deal_type == 'RENT':
        ads_qs = HouseForRent.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        ).order_by('-first_seen')
    elif deal_type == 'SELL':
        ads_qs = HouseForSale.objects.filter(
            region_id__in=region_ids,
            first_seen__date__gte=date_from,
            first_seen__date__lte=date_to,
        ).order_by('-first_seen')
    else:
        ads_qs = HouseForRent.objects.none()

    paginator = Paginator(ads_qs, 50)
    page_number = request.GET.get('page')
    ads = paginator.get_page(page_number)

    deal_type_choices = [('RENT', 'Rent'), ('SELL', 'Sell')]

    return render(request, 'classified_ads/house_region_ads_list.html', {
        'region': region,
        'ads': ads,
        'date_from': date_from,
        'date_to': date_to,
        'deal_type': deal_type,
        'deal_type_choices': deal_type_choices,
        'total_count': ads_qs.count(),
    })


def daily_sightings_report(request):
    default_from = date.today() - timedelta(days=30)
    default_to = date.today()

    date_from_str = (
        request.GET.get('date_from', '').strip()
        or default_from.isoformat()
    )
    date_to_str = (
        request.GET.get('date_to', '').strip()
        or default_to.isoformat()
    )
    order = request.GET.get('order', 'asc').strip()
    if order not in ['asc', 'desc']:
        order = 'asc'

    date_from = date.fromisoformat(date_from_str)
    date_to = date.fromisoformat(date_to_str)

    apartment_rent_sightings = (
        ApartmentForRentSighting.objects
        .filter(seen_on__gte=date_from, seen_on__lte=date_to)
        .values('seen_on')
        .annotate(count=Count('id'))
        .order_by('seen_on')
    )

    apartment_sale_sightings = (
        ApartmentForSaleSighting.objects
        .filter(seen_on__gte=date_from, seen_on__lte=date_to)
        .values('seen_on')
        .annotate(count=Count('id'))
        .order_by('seen_on')
    )

    house_rent_sightings = (
        HouseForRentSighting.objects
        .filter(seen_on__gte=date_from, seen_on__lte=date_to)
        .values('seen_on')
        .annotate(count=Count('id'))
        .order_by('seen_on')
    )

    house_sale_sightings = (
        HouseForSaleSighting.objects
        .filter(seen_on__gte=date_from, seen_on__lte=date_to)
        .values('seen_on')
        .annotate(count=Count('id'))
        .order_by('seen_on')
    )

    apartment_rent_by_date = {
        item['seen_on']: item['count']
        for item in apartment_rent_sightings
    }
    apartment_sale_by_date = {
        item['seen_on']: item['count']
        for item in apartment_sale_sightings
    }
    house_rent_by_date = {
        item['seen_on']: item['count']
        for item in house_rent_sightings
    }
    house_sale_by_date = {
        item['seen_on']: item['count']
        for item in house_sale_sightings
    }

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
            'grand_total': apt_rent + apt_sale + house_rent + house_sale,
        })

    return render(
        request,
        'classified_ads/daily_sightings_report.html',
        {
            'date_from': date_from_str,
            'date_to': date_to_str,
            'daily_data': daily_data,
            'order': order,
        }
    )

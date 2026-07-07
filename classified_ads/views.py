from django.core.paginator import Paginator
from django.shortcuts import render, redirect

from .models import ClassifiedAd, Region


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
            urls_to_enable = set(checked_urls)
            parent_regions = Region.objects.filter(
                url__in=checked_urls,
                parent__isnull=True
            ).prefetch_related('sub_regions')

            for parent in parent_regions:
                sub_region_urls = parent.sub_regions.values_list(
                    'url',
                    flat=True
                )
                urls_to_enable.update(sub_region_urls)

            Region.objects.filter(url__in=urls_to_enable).update(
                scrape_enabled=True
            )
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

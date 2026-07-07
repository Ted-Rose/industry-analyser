import time
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup
from django.core.paginator import Paginator
from django.shortcuts import render, redirect

from .models import ClassifiedAd, Region

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
        all_regions = _fetch_all_regions()

        for region_data in all_regions:
            parent_obj = None
            if region_data['parent_url']:
                parent_obj, _ = Region.objects.get_or_create(
                    url=region_data['parent_url'],
                    defaults={'name': region_data['parent_name']},
                )

            Region.objects.update_or_create(
                url=region_data['url'],
                defaults={
                    'name': region_data['name'],
                    'parent': parent_obj,
                    'scrape_enabled': region_data['url'] in checked_urls,
                },
            )

        return redirect('classified_ads:region_config')

    all_regions = _fetch_all_regions()
    existing_regions = {
        r.url: r for r in Region.objects.all()
    }

    for region_data in all_regions:
        if region_data['url'] in existing_regions:
            region_data['enabled'] = (
                existing_regions[region_data['url']].scrape_enabled
            )
        else:
            region_data['enabled'] = False

    top_level = [r for r in all_regions if not r['parent_url']]
    sub_regions_map = {}
    for r in all_regions:
        if r['parent_url']:
            if r['parent_url'] not in sub_regions_map:
                sub_regions_map[r['parent_url']] = []
            sub_regions_map[r['parent_url']].append(r)

    for region in top_level:
        region['sub_regions'] = sub_regions_map.get(region['url'], [])

    enabled_count = sum(1 for r in all_regions if r['enabled'])

    return render(request, 'classified_ads/region_config.html', {
        'regions_tree': top_level,
        'enabled_count': enabled_count,
        'total_count': len(all_regions),
    })


def _fetch_all_regions():
    base_url = 'https://www.ss.com/lv/real-estate/flats/'
    response = requests.get(base_url, timeout=10, verify=False)
    soup = BeautifulSoup(response.content, 'html.parser')

    all_regions = []
    top_level_links = soup.find_all('a', class_='a_category')

    for link in top_level_links:
        name = link.text.strip()
        relative_href = link.get('href', '')
        if '/all/' in relative_href:
            continue

        full_url = urljoin('https://www.ss.com', relative_href)
        en_url = full_url.replace('/lv/', '/en/')

        time.sleep(0.3)
        sub_response = requests.get(full_url, timeout=10, verify=False)
        sub_soup = BeautifulSoup(sub_response.content, 'html.parser')
        sub_links = sub_soup.find_all('a', class_='a_category')

        if not sub_links:
            all_regions.append({
                'name': name,
                'url': en_url,
                'parent_url': None,
                'parent_name': None,
            })
        else:
            for sub_link in sub_links:
                sub_name = sub_link.text.strip()
                sub_relative_href = sub_link.get('href', '')
                if '/all/' in sub_relative_href:
                    continue

                sub_full_url = urljoin('https://www.ss.com', sub_relative_href)
                sub_en_url = sub_full_url.replace('/lv/', '/en/')

                all_regions.append({
                    'name': sub_name,
                    'url': sub_en_url,
                    'parent_url': en_url,
                    'parent_name': name,
                })

    return all_regions

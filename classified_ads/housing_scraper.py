import logging
import re
from datetime import date
from typing import List

from django.utils import timezone

from bs4 import BeautifulSoup

from core_scraper.base import BaseScraper
from .models import (
    HouseForRent, HouseForRentSighting,
    HouseForSale, HouseForSaleSighting,
    Region, Seller,
)

logger = logging.getLogger('classified_ads')

HOUSING_BASE = (
    'https://www.ss.com/en/real-estate/homes-summer-residences/'
)

HOUSING_DEAL_SUFFIXES = {
    'hand_over/': 'RENT',
    'sell/': 'SELL',
}


def _parse_land_area(raw: str):
    """
    Convert land area string to m².
    Handles:  "239 m²", "0.11 ha.", "1200"
    Returns None if unparseable.
    """
    raw = raw.strip()
    if not raw or raw == '-':
        return None
    ha_match = re.search(r'([\d.,]+)\s*ha', raw, re.IGNORECASE)
    if ha_match:
        return float(ha_match.group(1).replace(',', '.')) * 10_000
    m2_match = re.search(r'([\d\s,]+)', raw)
    if m2_match:
        try:
            return float(
                m2_match.group(1).replace(',', '').replace(' ', '')
            )
        except ValueError:
            return None
    return None


class HousingAdScraper(BaseScraper):

    def __init__(self, max_pages=100):
        super().__init__()
        self.max_pages = max_pages
        self.enrich_search_results = True
        self.validate_result = False
        self.excluded_resources = []
        self._current_region = None
        self._current_deal_type = None

    def get_search_urls(self):
        regions = Region.objects.filter(scrape_enabled=True)
        if not regions.exists():
            logger.warning(
                'No regions enabled for scraping. '
                'Please configure regions via the admin interface.'
            )
            return

        for region in regions:
            if '/homes-summer-residences/' not in region.url:
                continue

            self._current_region = region
            for suffix, deal_type in HOUSING_DEAL_SUFFIXES.items():
                self._current_deal_type = deal_type

                for page in range(1, self.max_pages + 1):
                    if page == 1:
                        yield region.url + suffix
                    else:
                        yield (
                            region.url + suffix
                            + 'page' + str(page) + '.html'
                        )
                    if not self.last_search_had_results:
                        break

    def parse_results(self, response) -> List[dict]:
        if response is None:
            return []
        soup = BeautifulSoup(response.data, 'html.parser')
        results = []
        for row in soup.find_all('tr'):
            tds = row.find_all('td')
            cells = [td.text for td in tds]
            if len(cells) != 9:
                continue
            row_id = row.get('id')
            if not row_id:
                continue

            link = ''
            for a_tag in row.find_all('a'):
                href = a_tag.get('href', '')
                if href:
                    link = 'https://www.ss.com' + href
                    break

            total_price = self._clean_price(cells[8])

            deal_type = self._current_deal_type
            if deal_type == 'RENT':
                alt_price = float(total_price) * 120
            else:
                alt_price = total_price

            try:
                rooms_raw = cells[6]
                if len(str(rooms_raw)) > 2 or len(str(rooms_raw)) == 0:
                    rooms = 0
                elif len(str(rooms_raw)) > 0:
                    rooms = int(rooms_raw)
                else:
                    rooms = 0
            except (ValueError, TypeError):
                rooms = 0

            if rooms == 0 or total_price == 0.0:
                continue

            try:
                floors = int(float(cells[5]))
            except (ValueError, TypeError):
                floors = 0

            street_source = cells[3].strip()
            street_name, street_no = self._split_street(street_source)

            land_area_sqm = _parse_land_area(cells[7])

            ad_id = str(
                str(row_id)
                + cells[3]
                + cells[4]
                + cells[5]
                + cells[6]
                + cells[7]
            )

            results.append({
                'ad_id': ad_id,
                'deal_type': deal_type,
                'district': self._current_region.name,
                'region_name': self._current_region.name,
                'link': link,
                'comment': str(cells[2]),
                'street_name': street_name,
                'street_no': street_no,
                'rooms': rooms,
                'size': cells[4],
                'floors': floors,
                'land_area_sqm': land_area_sqm,
                'total_price': total_price,
                'alt_price': alt_price,
            })
        return results

    def _split_street(self, street_raw):
        street_raw = str(street_raw).strip()
        parts = street_raw.split(' ')
        if len(parts) > 1 and parts[-1][:1].isdigit():
            return ' '.join(parts[:-1]), parts[-1]
        return street_raw, ''

    def _clean_price(self, price_str) -> float:
        price_str = str(price_str).strip()
        if len(price_str) < 2 and price_str == '-':
            return 0.0
        if price_str in ('-', 'buy '):
            return 0.0
        try:
            if '/' not in price_str:
                return float(
                    price_str.replace(',', '')
                    .encode('ascii', 'ignore')
                )
            if '/day' in price_str:
                val = float(
                    price_str.replace('/day', '')
                    .replace(',', '')
                    .replace(' ', '')
                    .encode('ascii', 'ignore')
                )
                return val * 30
            if '/week' in price_str:
                val = float(
                    price_str.replace('/week', '')
                    .replace(',', '')
                    .replace(' ', '')
                    .encode('ascii', 'ignore')
                )
                return val * 4
            return float(
                price_str.replace('/mon.', '')
                .replace(',', '')
                .replace(' ', '')
                .encode('ascii', 'ignore')
            )
        except (ValueError, TypeError):
            return 0.0

    def remove_redundant_results(self, resources):
        if not resources:
            return resources

        rent_incoming = {
            r['ad_id'] for r in resources if r['deal_type'] == 'RENT'
        }
        sell_incoming = {
            r['ad_id'] for r in resources if r['deal_type'] == 'SELL'
        }

        existing_rent_ids = set(
            HouseForRent.objects.filter(
                ad_id__in=rent_incoming
            ).values_list('ad_id', flat=True)
        ) if rent_incoming else set()

        existing_sell_ids = set(
            HouseForSale.objects.filter(
                ad_id__in=sell_incoming
            ).values_list('ad_id', flat=True)
        ) if sell_incoming else set()

        if existing_rent_ids:
            self._write_sightings(existing_rent_ids, 'RENT')
        if existing_sell_ids:
            self._write_sightings(existing_sell_ids, 'SELL')

        existing_ids = existing_rent_ids | existing_sell_ids
        return [r for r in resources if r['ad_id'] not in existing_ids]

    def enrich_result(self, partial_result):
        detail_response = self.make_request(partial_result['link'])
        if detail_response is None:
            return partial_result

        soup = BeautifulSoup(detail_response.data, 'html.parser')

        post_date = None
        seller_phone = ''
        seller_contact_id = ''

        for row in soup.find_all('tr'):
            tds = row.find_all('td')
            if len(tds) < 2:
                continue
            label = tds[0].text.strip()
            value = tds[1].text.strip()

            if 'Date' in label or 'Datums' in label:
                try:
                    post_date = timezone.make_aware(
                        timezone.datetime.strptime(value, '%d.%m.%Y')
                    )
                except (ValueError, TypeError):
                    pass
            elif 'Phone' in label or 'Tālrunis' in label:
                seller_phone = value
            elif 'Contact' in label or 'Kontakts' in label:
                seller_contact_id = value

        partial_result['post_date'] = post_date
        partial_result['seller_phone'] = seller_phone
        partial_result['seller_contact_id'] = seller_contact_id

        return partial_result

    def initiate_resource(self, result):
        seller = None
        if result.get('seller_phone') or result.get('seller_contact_id'):
            seller, _ = Seller.objects.get_or_create(
                phone=result.get('seller_phone', ''),
                contact_id=result.get('seller_contact_id', ''),
            )

        try:
            size_val = float(result['size'])
        except (ValueError, TypeError):
            size_val = 0.0

        price_per_sqm = (
            result['total_price'] / size_val if size_val > 0 else 0.0
        )

        deal_type = result['deal_type']
        if deal_type == 'RENT':
            monthly_price = result['total_price']
            monthly_price_per_sqm = price_per_sqm
            total_price_120m = result['alt_price']
            price_per_sqm_120m = (
                total_price_120m / size_val if size_val > 0 else 0.0
            )

            return HouseForRent(
                ad_id=result['ad_id'],
                comment=result['comment'],
                link=result['link'],
                region=self._current_region,
                region_name=result['region_name'],
                district=result['district'],
                street_name=result['street_name'],
                street_no=result['street_no'],
                rooms=result['rooms'],
                size=size_val,
                floors=result['floors'],
                land_area_sqm=result.get('land_area_sqm'),
                post_date=result.get('post_date'),
                seller=seller,
                price_per_sqm=price_per_sqm,
                total_price=result['total_price'],
                monthly_price=monthly_price,
                monthly_price_per_sqm=monthly_price_per_sqm,
                total_price_120m=total_price_120m,
                price_per_sqm_120m=price_per_sqm_120m,
            )
        elif deal_type == 'SELL':
            return HouseForSale(
                ad_id=result['ad_id'],
                comment=result['comment'],
                link=result['link'],
                region=self._current_region,
                region_name=result['region_name'],
                district=result['district'],
                street_name=result['street_name'],
                street_no=result['street_no'],
                rooms=result['rooms'],
                size=size_val,
                floors=result['floors'],
                land_area_sqm=result.get('land_area_sqm'),
                post_date=result.get('post_date'),
                seller=seller,
                price_per_sqm=price_per_sqm,
                total_price=result['total_price'],
            )

        return None

    def create_or_update_resources(self, resources):
        if not resources:
            return

        rent_ads = [r for r in resources if isinstance(r, HouseForRent)]
        sell_ads = [r for r in resources if isinstance(r, HouseForSale)]

        if rent_ads:
            HouseForRent.objects.bulk_create(
                rent_ads, ignore_conflicts=True
            )
            rent_ids = {ad.ad_id for ad in rent_ads}
            self._write_sightings(rent_ids, 'RENT')

        if sell_ads:
            HouseForSale.objects.bulk_create(
                sell_ads, ignore_conflicts=True
            )
            sell_ids = {ad.ad_id for ad in sell_ads}
            self._write_sightings(sell_ids, 'SELL')

    def _write_sightings(self, ad_ids, deal_type):
        today = date.today()

        if deal_type == 'RENT':
            existing_ads = HouseForRent.objects.filter(
                ad_id__in=ad_ids
            ).values_list('id', 'ad_id')
            ad_map = {ad_id: pk for pk, ad_id in existing_ads}

            existing_sightings = set(
                HouseForRentSighting.objects.filter(
                    ad_id__in=ad_map.values(),
                    seen_on=today,
                ).values_list('ad_id', flat=True)
            )

            new_sightings = [
                HouseForRentSighting(ad_id=ad_map[ad_id], seen_on=today)
                for ad_id in ad_ids
                if ad_id in ad_map and ad_map[ad_id] not in
                existing_sightings
            ]

            if new_sightings:
                HouseForRentSighting.objects.bulk_create(
                    new_sightings, ignore_conflicts=True
                )

        elif deal_type == 'SELL':
            existing_ads = HouseForSale.objects.filter(
                ad_id__in=ad_ids
            ).values_list('id', 'ad_id')
            ad_map = {ad_id: pk for pk, ad_id in existing_ads}

            existing_sightings = set(
                HouseForSaleSighting.objects.filter(
                    ad_id__in=ad_map.values(),
                    seen_on=today,
                ).values_list('ad_id', flat=True)
            )

            new_sightings = [
                HouseForSaleSighting(ad_id=ad_map[ad_id], seen_on=today)
                for ad_id in ad_ids
                if ad_id in ad_map and ad_map[ad_id] not in
                existing_sightings
            ]

            if new_sightings:
                HouseForSaleSighting.objects.bulk_create(
                    new_sightings, ignore_conflicts=True
                )

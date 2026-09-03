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

    def _get_last_scraped_region_id(self, today):
        """
        Get the ID of the last region that was scraped today.
        This helps us resume from the right place if interrupted.
        """
        # Get the most recent sighting from today across both models
        last_rent = (
            HouseForRentSighting.objects
            .filter(seen_on=today)
            .select_related('ad__region')
            .order_by('-id')
            .first()
        )
        last_sale = (
            HouseForSaleSighting.objects
            .filter(seen_on=today)
            .select_related('ad__region')
            .order_by('-id')
            .first()
        )

        # Return the region ID from the most recent sighting
        if last_rent and last_sale:
            # Compare which is more recent and return that region
            rent_region_id = last_rent.ad.region_id
            sale_region_id = last_sale.ad.region_id
            # Return the max ID (later in the ordered list)
            return max(rent_region_id, sale_region_id)
        elif last_rent:
            return last_rent.ad.region_id
        elif last_sale:
            return last_sale.ad.region_id
        return None

    def get_search_urls(self):
        # Fetch regions in consistent order (using model's Meta.ordering)
        regions = Region.objects.filter(scrape_enabled=True).order_by('id')
        if not regions.exists():
            logger.warning(
                'No regions enabled for scraping. '
                'Please configure regions via the admin interface.'
            )
            return

        today = date.today()

        # Find the last region that was scraped today
        last_scraped_region_id = self._get_last_scraped_region_id(today)

        # Determine where to start scraping
        start_scraping = last_scraped_region_id is None

        for region in regions:
            if '/homes-summer-residences/' not in region.url:
                continue

            # If we haven't started yet, skip until we reach the last
            # scraped region
            if not start_scraping:
                if region.id == last_scraped_region_id:
                    # Re-scrape this region (might have been interrupted)
                    start_scraping = True
                    logger.info(
                        f"Resuming from region '{region.name}' "
                        f"(last scraped today)"
                    )
                else:
                    logger.info(
                        f"Skipping region '{region.name}' - "
                        f"already completed today"
                    )
                    continue

            self._current_region = region
            logger.info(f"Scraping region: {region.name}")

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

            if total_price == 0.0:
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
                'rooms': 0,
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

        # Extract post date from msg_footer
        # Support both English "Date:" and Latvian "Datums:"
        date_labels = ('Date:', 'Datums:')
        for td in soup.find_all('td', 'msg_footer'):
            text = td.text.strip()

            # Check if this footer contains a date label
            date_label_found = None
            for label in date_labels:
                if label in text:
                    date_label_found = label
                    break

            if date_label_found:
                # Extract the date part after the label
                raw = text.split(date_label_found, 1)[1].strip()
                try:
                    naive = timezone.datetime.strptime(
                        raw, '%d.%m.%Y %H:%M'
                    )
                    post_date = timezone.make_aware(naive)
                except (ValueError, TypeError):
                    pass
                break

        # Extract phone number
        prefix_span = soup.find(
            'span', id=re.compile(r'^phone_td_')
        )
        if prefix_span:
            seller_phone = prefix_span.get_text(strip=True)

        # Extract contact ID from mail link
        mail_link = soup.find(
            'a', href=re.compile(r'/mail/')
        )
        if mail_link:
            href = mail_link.get('href', '')
            seller_contact_id = (
                href.split('/')[-1].replace('.html', '')
            )

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

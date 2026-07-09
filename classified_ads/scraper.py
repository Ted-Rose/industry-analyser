import logging
import re
from datetime import date, datetime
from typing import List

from django.utils import timezone

from bs4 import BeautifulSoup

from core_scraper.base import BaseScraper
from .models import ClassifiedAd, ClassifiedAdSighting, Region, Seller

logger = logging.getLogger('classified_ads')

DEAL_SUFFIXES = {
    'hand_over/': ClassifiedAd.DEAL_RENT,
    'sell/': ClassifiedAd.DEAL_SELL,
}


class SsComScraper(BaseScraper):

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
            self._current_region = region
            for suffix, deal_type in DEAL_SUFFIXES.items():
                self._current_deal_type = deal_type

                # Max pages is a random, high number. Once first empty result
                # page is returned stop scraping current deal type for
                # the region.
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
            if len(cells) != 10:
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

            sqm_price = self._clean_price(cells[8])
            total_price = self._clean_price(cells[9])

            deal_type = self._current_deal_type
            if deal_type == ClassifiedAd.DEAL_RENT:
                alt_price = float(total_price) * 120
                alt_price_per_sqm = float(sqm_price) * 120
            else:
                alt_price = total_price
                alt_price_per_sqm = sqm_price

            try:
                rooms_raw = cells[4]
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

            floor_raw = str(cells[6]).split('/')
            try:
                floor = int(float(floor_raw[0]))
            except (ValueError, TypeError):
                floor = 0
            try:
                max_floor = int(float(floor_raw[-1]))
            except (ValueError, TypeError):
                max_floor = 0

            # The address cell stacks the village/town on its own line
            # above the street, e.g. "Kadaga\nKadagas 9" - td.text merges
            # those with no separator, so re-extract with a line break
            # and only split the last line (the actual street).
            address_lines = [
                line.strip()
                for line in tds[3].get_text('\n').split('\n')
                if line.strip()
            ]
            street_source = address_lines[-1] if address_lines else ''
            street_name, street_no = self._split_street(street_source)

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
                'size': cells[5],
                'floor': floor,
                'max_floor': max_floor,
                'project': str(cells[7]),
                'price_per_sqm': sqm_price,
                'alt_price_per_sqm': alt_price_per_sqm,
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
        # TODO: Here existing records shouldn't be regarded as redundant
        # As we need to record their recurrence in ClassifiedAdSighting table
        if not resources:
            return resources
        incoming_ids = [r['ad_id'] for r in resources]
        existing_ids = set(
            ClassifiedAd.objects.filter(
                ad_id__in=incoming_ids
            ).values_list('ad_id', flat=True)
        )
        return [r for r in resources if r['ad_id'] not in existing_ids]

    def enrich_result(self, partial_result):
        # TODO: For existing records no need to make API request - just record
        # recurrence fact
        detail_response = self.make_request(partial_result['link'])
        detail = self._parse_detail_page(detail_response)
        return {**partial_result, **detail}

    def get_resource_info_link(self, partial_result):
        return partial_result['link']

    def initiate_resource(self, enriched_result):
        phone = enriched_result.get('phone', '')
        contact_id = enriched_result.get('contact_id', '')
        seller = None
        if phone or contact_id:
            seller, _ = Seller.objects.get_or_create(
                phone=phone, contact_id=contact_id
            )
        return ClassifiedAd(
            ad_id=enriched_result['ad_id'],
            deal_type=enriched_result['deal_type'],
            comment=enriched_result.get('comment', ''),
            link=enriched_result['link'],
            region=self._current_region,
            region_name=enriched_result['region_name'],
            district=enriched_result['district'],
            street_name=enriched_result['street_name'],
            street_no=enriched_result.get('street_no', ''),
            rooms=enriched_result['rooms'],
            size=enriched_result['size'],
            floor=enriched_result['floor'],
            max_floor=enriched_result['max_floor'],
            project=enriched_result['project'],
            house_type=enriched_result.get('house_type', ''),
            facilities=enriched_result.get('facilities', ''),
            post_date=enriched_result.get('post_date'),
            seller=seller,
            price_per_sqm=enriched_result['price_per_sqm'],
            alt_price_per_sqm=enriched_result['alt_price_per_sqm'],
            total_price=enriched_result['total_price'],
            alt_price=enriched_result['alt_price'],
        )

    def create_or_update_resources(self, ads):
        if not ads:
            return
        # TODO: Here somehow we have to create new ads and add
        # new records in ClassifiedAdSighting table for existing ads
        # though it has to be ensured that there isn't made more than
        # one record for each date in ClassifiedAdSighting table for
        # single resource - meaning that there aren't two entries
        # for a single resource with date July 19th (thus the model
        # has to be updated with this guard)
        ClassifiedAd.objects.bulk_create(
            ads,
            update_conflicts=True,
            unique_fields=['ad_id'],
            update_fields=[
                'comment', 'link', 'price_per_sqm',
                'alt_price_per_sqm', 'total_price',
                'alt_price', 'post_date', 'last_seen',
                'seller', 'house_type', 'facilities',
            ],
        )
        logger.info(f"Saved {len(ads)} classified ads.")
        self._write_sightings([ad.ad_id for ad in ads])

    def _write_sightings(self, ad_ids):
        today = date.today()
        ads = ClassifiedAd.objects.filter(ad_id__in=ad_ids)
        sightings = [
            ClassifiedAdSighting(ad=ad, seen_on=today)
            for ad in ads
        ]
        ClassifiedAdSighting.objects.bulk_create(
            sightings,
            ignore_conflicts=True,
        )
        logger.info(
            f"Recorded {len(sightings)} sightings for {today}."
        )

    def _parse_detail_page(self, response) -> dict:
        result = {
            'post_date': None,
            'phone': '',
            'contact_id': '',
            'comment': '',
        }
        if response is None:
            return result
        # lxml recovers from the unclosed <td>/<tr> tags on this page's
        # attribute table far more reliably than html.parser, which was
        # letting later rows' text bleed into earlier ones (e.g. the
        # Street value ending up prefixed with the Township value).
        soup = BeautifulSoup(response.data, 'lxml')

        msg_div = soup.find('div', id='msg_div_msg')
        if msg_div:
            for tag in msg_div.find_all(['table', 'div']):
                tag.decompose()
            result['comment'] = msg_div.get_text(
                separator='\n', strip=True
            )

        for td in soup.find_all('td', 'msg_footer'):
            if 'Date' in td.text:
                raw = td.text[6:].strip()
                try:
                    naive = datetime.strptime(
                        raw, '%d.%m.%Y %H:%M'
                    )
                    result['post_date'] = (
                        timezone.make_aware(naive)
                    )
                except ValueError:
                    pass
                break

        prefix_span = soup.find(
            'span', id=re.compile(r'^phone_td_')
        )
        if prefix_span:
            result['phone'] = prefix_span.get_text(strip=True)

        mail_link = soup.find(
            'a', href=re.compile(r'/mail/')
        )
        if mail_link:
            href = mail_link.get('href', '')
            result['contact_id'] = (
                href.split('/')[-1].replace('.html', '')
            )

        # ss.com serves this page in whatever language the request's
        # locale path uses (e.g. /lv/ -> "Iela:" instead of "Street:").
        street_labels = ('Street:', 'Iela:')
        for label_td in soup.find_all('td', class_='ads_opt_name'):
            if label_td.get_text(strip=True) not in street_labels:
                continue
            value_td = label_td.find_next_sibling(
                'td', class_='ads_opt'
            )
            if value_td:
                bold = value_td.find('b')
                target = bold if bold else value_td
                # Only the tag's own text, not text pulled in from
                # nested/mis-nested tags (e.g. the "[Map]" link, or
                # content from adjacent rows on malformed pages).
                street_text = ''.join(
                    target.find_all(string=True, recursive=False)
                ).strip()
                result['street_name'], result['street_no'] = (
                    self._split_street(street_text)
                )
            break

        result['house_type'] = self._ads_opt_value(soup, 'House type:')
        result['facilities'] = self._ads_opt_value(soup, 'Facilities:')

        return result

    def _ads_opt_value(self, soup, label):
        for label_td in soup.find_all('td', class_='ads_opt_name'):
            if label_td.get_text(strip=True) != label:
                continue
            value_td = label_td.find_next_sibling(
                'td', class_='ads_opt'
            )
            if not value_td:
                return ''
            bold = value_td.find('b')
            target = bold if bold else value_td
            return ''.join(
                target.find_all(string=True, recursive=False)
            ).strip()
        return ''

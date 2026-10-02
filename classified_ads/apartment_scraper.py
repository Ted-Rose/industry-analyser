import logging
import re
from datetime import date, datetime
from typing import List

from django.utils import timezone

from bs4 import BeautifulSoup

from core_scraper.base import BaseScraper
from .models import (
    ApartmentForRent, ApartmentForRentSighting,
    ApartmentForSale, ApartmentForSaleSighting,
    Project, Region, Seller,
)

logger = logging.getLogger('classified_ads')

DEAL_SUFFIXES = {
    'hand_over/': 'RENT',
    'sell/': 'SELL',
}

PRICE_THRESHOLD = 50
SALE_KEYWORDS = [
    'pārdod', 'pārdošan', 'pārdots', 'izpirkum', 'pirkt',
    'pardod', 'pardosan', 'pardots',
    'продаётся', 'Продаем', 'Продается', 'Продам',
]


def is_sale_misclassified(comment, monthly_price_per_sqm):
    """
    Check if a rental ad is actually a for-sale listing (Strategy C+).

    Two complementary signals:
    1. Price signal: monthly_price_per_sqm > 50 (sale price entered as rent)
    2. Keyword signal: Latvian/Russian sale vocabulary in comment

    See: docs/misclassified_sale_ads_analysis.md
    """
    if monthly_price_per_sqm > PRICE_THRESHOLD:
        return True

    comment_lower = comment.lower()
    for keyword in SALE_KEYWORDS:
        if keyword.lower() in comment_lower:
            return True

    return False


class ApartmentAdScraper(BaseScraper):

    PROJECT_MAPPINGS = {
        '103-th': 'Series 103',
        '103.': 'Series 103',
        '602-th': 'Series 602',
        '602.': 'Series 602',
        '467-th': 'Series 467',
        '467.': 'Series 467',
        '119-th': 'Series 119',
        '119.': 'Series 119',
        '104-th': 'Series 104',
        '104.': 'Series 104',
        'Spec. pr.': 'Special Project',
        'Specpr.': 'Special Project',
        'Chrusch.': 'Khrushchyovka',
        'Hrušč.': 'Khrushchyovka',
        'Czech pr.': 'Czech Project',
        'Čehu pr.': 'Czech Project',
        'Lit pr.': 'Lithuanian Project',
        'LT proj.': 'Lithuanian Project',
        'Stalin project': 'Stalin Era',
        'Staļina': 'Stalin Era',
        'Recon.': 'Renovated',
        'Renov.': 'Renovated',
        'New': 'New Construction',
        'Jaun.': 'New Construction',
        'Sm.fam.': 'Small Family House',
        'M. ģim.': 'Small Family House',
        'Priv.house': 'Private House',
        'Priv. m.': 'Private House',
        'Pre-war house': 'Pre-War',
        'P. kara': 'Pre-War',
        '-': 'Unknown',
    }

    def __init__(self, max_pages=100, runner=None, dry_run=False):
        super().__init__()
        self.max_pages = max_pages
        self.runner = runner
        self.dry_run = dry_run
        self.enrich_search_results = True
        self.validate_result = False
        self.stop_on_redirect = True
        self.excluded_resources = []
        self._current_region = None
        self._current_deal_type = None
        self._seen_ad_ids = set()

    def get_search_urls(self):
        # Fetch regions in consistent order (using model's Meta.ordering)
        regions = Region.objects.filter(scrape_enabled=True).order_by('id')
        if not regions.exists():
            logger.warning(
                'No regions enabled for scraping. '
                'Please configure regions via the admin interface.'
            )
            return

        if self.runner is None:
            # No checkpointing wired up — a plain full pass over every
            # enabled region.
            for region in regions:
                self._current_region = region
                logger.info(f"Scraping region: {region.name}")
                yield from self._region_search_urls(region)
            return

        entries = [
            (
                str(region.id),
                region.name,
                self._region_priority(region),
                region,
            )
            for region in regions
        ]
        items = self.runner.sync_items(entries)
        for item in self.runner.pending_items(items):
            region = item.obj
            self._current_region = region
            logger.info(f"Scraping region: {region.name}")
            try:
                yield from self._region_search_urls(region)
            except Exception as e:
                # run() throws scrape_portal() failures back in here —
                # record the item and continue with the next region.
                self.runner.item_failed(item, e)
                continue
            self.runner.item_done(item)

    @staticmethod
    def _region_priority(region):
        try:
            return int(region.order_id)
        except (ValueError, TypeError):
            return 0

    def _region_search_urls(self, region):
        """Yield one region's listing URLs (deal types x pages).

        Max pages is a random, high number. Once first empty
        result page is returned stop scraping current deal
        type for the region.
        """
        for suffix, deal_type in DEAL_SUFFIXES.items():
            self._current_deal_type = deal_type
            self._seen_ad_ids = set()
            for page in range(1, self.max_pages + 1):
                if page == 1:
                    yield region.url + suffix
                else:
                    yield (
                        region.url + suffix
                        + 'page' + str(page) + '.html'
                    )
                if self.runner is not None:
                    self.runner.touch()
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
            # The same ad is linked under /msg/lv/ on some listing
            # pages and /msg/en/ on others; pin to /en/ so the stored
            # link stops flip-flopping between scrapes.
            link = link.replace('/msg/lv/', '/msg/en/')

            sqm_price = self._clean_price(cells[8])
            total_price = self._clean_price(cells[9])
            size = self._clean_size(cells[5])

            deal_type = self._current_deal_type
            if deal_type == 'RENT':
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

            if rooms == 0 or total_price == 0.0 or size == 0.0:
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
            street_name, street_no, apartment_no = (
                self._split_street(street_source)
            )

            # The tr_ row id alone is ss.com's stable, globally-unique
            # ad id. Appending listing-cell text minted a new ad_id on
            # every address/size/language variant, which defeated
            # unique dedup (see docs/ad_id_dedup_fix_plan.md).
            ad_id = str(row_id)

            results.append({
                'ad_id': ad_id,
                'deal_type': deal_type,
                'district': self._current_region.name,
                'region_name': self._current_region.name,
                'link': link,
                'comment': str(cells[2]),
                'street_name': street_name,
                'street_no': street_no,
                'apartment_no': apartment_no,
                'rooms': rooms,
                'size': size,
                'floor': floor,
                'max_floor': max_floor,
                'project_raw': str(cells[7]),
                'project': self._get_or_create_project(str(cells[7])),
                'price_per_sqm': sqm_price,
                'alt_price_per_sqm': alt_price_per_sqm,
                'total_price': total_price,
                'alt_price': alt_price,
            })

        # ss.com redirects out-of-range pages back to the first
        # listing page (handled by stop_on_redirect); if a repeated
        # page is ever served as 200, identical ad ids mean the end
        # of this region's results has been reached.
        new_results = [
            r for r in results if r['ad_id'] not in self._seen_ad_ids
        ]
        self._seen_ad_ids.update(r['ad_id'] for r in results)
        if results and not new_results:
            logger.info(
                'Page repeats already-scraped ads — '
                'end of results reached'
            )
        return new_results

    def _get_or_create_project(self, raw_project: str):
        raw = str(raw_project).strip()
        if not raw:
            return None
        normalized_name = self.PROJECT_MAPPINGS.get(raw, None)
        if normalized_name:
            project, _ = Project.objects.get_or_create(
                name=normalized_name
            )
            return project
        logger.warning(f"Unmapped project type: '{raw}'")
        return None

    def _split_street(self, street_raw):
        """
        Parse street address into components.

        Handles formats like:
        - "Aldaunes iela 2 17" -> ("Aldaunes iela", "2", "17")
        - "Miera 3 1" -> ("Miera", "3", "1")
        - "Brivibas 123" -> ("Brivibas", "123", "")
        - "Main Street" -> ("Main Street", "", "")

        Returns:
            tuple: (street_name, street_no, apartment_no)
        """
        street_raw = str(street_raw).strip()
        parts = street_raw.split(' ')

        if len(parts) == 1:
            return street_raw, '', ''

        apartment_no = ''
        if parts[-1][:1].isdigit():
            apartment_no = parts[-1]
            parts = parts[:-1]

        street_no = ''
        if len(parts) > 1 and parts[-1][:1].isdigit():
            street_no = parts[-1]
            parts = parts[:-1]
        elif apartment_no and not street_no:
            street_no = apartment_no
            apartment_no = ''

        street_name = ' '.join(parts)
        return street_name, street_no, apartment_no

    def _clean_size(self, size_str) -> float:
        """Convert size string to float, handling '-' and invalid values."""
        size_str = str(size_str).strip()
        if size_str == '-' or not size_str:
            return 0.0
        try:
            return float(size_str.replace(',', ''))
        except (ValueError, TypeError):
            return 0.0

    def _clean_price(self, price_str) -> float:
        price_str = str(price_str).strip()
        if len(price_str) < 2 and price_str == '-':
            return 0.0
        if price_str in ('-', 'buy '):
            return 0.0
        try:
            cleaned = (
                price_str.replace('€', '')
                .replace('$', '')
                .replace(',', '')
                .replace(' ', '')
            )
            if '/' not in cleaned:
                return float(cleaned)
            if '/day' in cleaned or '/dienā' in cleaned:
                val = float(
                    cleaned.replace('/day', '')
                    .replace('/dienā', '')
                )
                return val * 30
            if '/week' in cleaned or '/nedēļā' in cleaned:
                val = float(
                    cleaned.replace('/week', '')
                    .replace('/nedēļā', '')
                )
                return val * 4
            return float(
                cleaned.replace('/mon.', '')
                .replace('/mn.', '')
                .replace('/mēn.', '')
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
            ApartmentForRent.all_objects.filter(
                ad_id__in=rent_incoming
            ).values_list('ad_id', flat=True)
        ) if rent_incoming else set()

        existing_sell_ids = set(
            ApartmentForSale.all_objects.filter(
                ad_id__in=sell_incoming
            ).values_list('ad_id', flat=True)
        ) if sell_incoming else set()

        # Existing ads are dropped from the pipeline below (no enrichment
        # request, no re-creation), but they're still active listings, so
        # record today's recurrence for them here instead.
        if existing_rent_ids:
            self._write_sightings(existing_rent_ids, 'RENT')
        if existing_sell_ids:
            self._write_sightings(existing_sell_ids, 'SELL')

        existing_ids = existing_rent_ids | existing_sell_ids
        return [r for r in resources if r['ad_id'] not in existing_ids]

    def enrich_result(self, partial_result):
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

        common_kwargs = dict(
            ad_id=enriched_result['ad_id'],
            comment=enriched_result.get('comment', ''),
            link=enriched_result['link'],
            region=self._current_region,
            region_name=enriched_result['region_name'],
            district=enriched_result['district'],
            street_name=enriched_result['street_name'],
            street_no=enriched_result.get('street_no', ''),
            apartment_no=enriched_result.get('apartment_no', ''),
            rooms=enriched_result['rooms'],
            size=enriched_result['size'],
            floor=enriched_result['floor'],
            max_floor=enriched_result['max_floor'],
            project_raw=enriched_result['project_raw'],
            project=enriched_result.get('project'),
            house_type=enriched_result.get('house_type', ''),
            facilities=enriched_result.get('facilities', ''),
            post_date=enriched_result.get('post_date'),
            seller=seller,
            price_per_sqm=enriched_result['price_per_sqm'],
            total_price=enriched_result['total_price'],
        )

        if enriched_result['deal_type'] == 'RENT':
            monthly_price_per_sqm = enriched_result['price_per_sqm']
            comment = enriched_result.get('comment', '')

            return ApartmentForRent(
                **common_kwargs,
                monthly_price=enriched_result['total_price'],
                monthly_price_per_sqm=monthly_price_per_sqm,
                total_price_120m=enriched_result['alt_price'],
                price_per_sqm_120m=enriched_result['alt_price_per_sqm'],
                is_sale_misclassified=is_sale_misclassified(
                    comment, monthly_price_per_sqm
                ),
            )
        return ApartmentForSale(**common_kwargs)

    def create_or_update_resources(self, ads):
        if not ads:
            return

        rent_ads = [a for a in ads if isinstance(a, ApartmentForRent)]
        sell_ads = [a for a in ads if isinstance(a, ApartmentForSale)]

        if self.dry_run:
            logger.info(
                '[dry-run] Would save %d rent ad(s) and %d sale ad(s).',
                len(rent_ads), len(sell_ads),
            )
            return

        if rent_ads:
            ApartmentForRent.all_objects.bulk_create(
                rent_ads,
                update_conflicts=True,
                unique_fields=['ad_id'],
                update_fields=[
                    'comment', 'link', 'price_per_sqm',
                    'monthly_price', 'monthly_price_per_sqm',
                    'total_price_120m', 'price_per_sqm_120m',
                    'total_price', 'post_date', 'last_seen',
                    'seller', 'house_type', 'facilities',
                    'is_sale_misclassified', 'apartment_no',
                ],
            )
            logger.info(f"Saved {len(rent_ads)} rent ads.")
            self._write_sightings(
                [ad.ad_id for ad in rent_ads], 'RENT'
            )

        if sell_ads:
            ApartmentForSale.all_objects.bulk_create(
                sell_ads,
                update_conflicts=True,
                unique_fields=['ad_id'],
                update_fields=[
                    'comment', 'link', 'price_per_sqm',
                    'total_price', 'post_date', 'last_seen',
                    'seller', 'house_type', 'facilities',
                    'apartment_no',
                ],
            )
            logger.info(f"Saved {len(sell_ads)} sale ads.")
            self._write_sightings(
                [ad.ad_id for ad in sell_ads], 'SELL'
            )

    def _write_sightings(self, ad_ids, deal_type):
        today = date.today()
        if self.dry_run:
            logger.info(
                '[dry-run] Would record %d %s sighting(s) for %s.',
                len(ad_ids), deal_type, today,
            )
            return
        if deal_type == 'RENT':
            ads = ApartmentForRent.all_objects.filter(ad_id__in=ad_ids)
            sightings = [
                ApartmentForRentSighting(ad=ad, seen_on=today)
                for ad in ads
            ]
            ApartmentForRentSighting.objects.bulk_create(
                sightings,
                ignore_conflicts=True,
            )
        else:
            ads = ApartmentForSale.all_objects.filter(ad_id__in=ad_ids)
            sightings = [
                ApartmentForSaleSighting(ad=ad, seen_on=today)
                for ad in ads
            ]
            ApartmentForSaleSighting.objects.bulk_create(
                sightings,
                ignore_conflicts=True,
            )
        logger.info(
            f"Recorded {len(sightings)} sightings for {today}."
        )

    def _parse_detail_for_refetch(self, response):
        """
        Parse detail page for refetch operation.
        Returns only the fields that can be updated from the detail page.
        """
        detail = self._parse_detail_page(response)

        phone = detail.get('phone', '')
        contact_id = detail.get('contact_id', '')

        if phone or contact_id:
            seller, _ = Seller.objects.get_or_create(
                phone=phone, contact_id=contact_id
            )
            detail['seller'] = seller
        else:
            detail['seller'] = None

        return detail

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

        # Support both English "Date:" and Latvian "Datums:"
        # ss.com serves pages in different languages based on the URL path
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
                (result['street_name'], result['street_no'],
                 result['apartment_no']) = (
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

import logging
import re
from datetime import date, datetime
from typing import List
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from bs4 import BeautifulSoup

from core_scraper.base import BaseScraper
from .models import (
    HouseForRent, HouseForRentSighting,
    HouseForSale, HouseForSaleSighting,
    Region, Seller,
)
from .rent_flags import (
    SHORT_STAY_PERIODS, detect_rate_period, is_room_share,
)
from .sale_flags import is_sale_misclassified

logger = logging.getLogger('classified_ads')

HOUSING_BASE = (
    'https://www.ss.com/en/real-estate/homes-summer-residences/'
)

HOUSING_DEAL_SUFFIXES = {
    'hand_over/': 'RENT',
    'sell/': 'SELL',
}

# Listings at or below this floor area are sheds/garages/land
# scraps, not houses — they are still stored (sightings, audit)
# but created is_hidden=True so the default manager never
# surfaces them. Mirrors the quarantine criteria in
# scripts/quarantine_junk_ads.py.
MIN_HOUSE_SIZE_SQM = 5.0


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

        housing_regions = [
            region for region in regions
            if '/homes-summer-residences/' in region.url
        ]

        if self.runner is None:
            # No checkpointing wired up — a plain full pass over every
            # enabled housing region.
            for region in housing_regions:
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
            for region in housing_regions
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
        for suffix, deal_type in HOUSING_DEAL_SUFFIXES.items():
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
            # The same ad is linked under /msg/lv/ on some listing
            # pages and /msg/en/ on others; pin to /en/ so the stored
            # link stops flip-flopping between scrapes.
            link = link.replace('/msg/lv/', '/msg/en/')

            total_price = self._clean_price(cells[8])

            deal_type = self._current_deal_type
            if deal_type == 'RENT':
                alt_price = float(total_price) * 120
            else:
                alt_price = total_price

            size = self._clean_size(cells[4])

            # size<=0 rows are unparseable/non-physical junk —
            # drop them outright (same guard as the apartment
            # scraper). Tiny-but-positive sizes are kept and
            # flagged is_hidden in initiate_resource instead.
            if total_price == 0.0 or size <= 0.0:
                continue

            try:
                floors = int(float(cells[5]))
            except (ValueError, TypeError):
                floors = 0

            street_source = cells[3].strip()
            street_name, street_no = self._split_street(street_source)

            land_area_sqm = _parse_land_area(cells[7])

            # The tr_ row id alone is ss.com's stable, globally-unique
            # ad id. Appending listing-cell text minted a new ad_id on
            # every address/size/language variant, which defeated
            # unique dedup (see docs/plans/ad_id_dedup_fix_plan.md).
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
                'rooms': 0,
                'size': size,
                'floors': floors,
                'land_area_sqm': land_area_sqm,
                'total_price': total_price,
                'alt_price': alt_price,
                # Raw cell keeps the billing-period marker that
                # _clean_price monthlyizes and drops — record it
                # here, the last point it is observable.
                'rate_period': detect_rate_period(cells[8]),
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

    def _split_street(self, street_raw):
        street_raw = str(street_raw).strip()
        parts = street_raw.split(' ')
        if len(parts) > 1 and parts[-1][:1].isdigit():
            return ' '.join(parts[:-1]), parts[-1]
        return street_raw, ''

    def _clean_size(self, size_str) -> float:
        """Convert size string to float; '-'/invalid -> 0.0."""
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
            HouseForRent.all_objects.filter(
                ad_id__in=rent_incoming
            ).values_list('ad_id', flat=True)
        ) if rent_incoming else set()

        existing_sell_ids = set(
            HouseForSale.all_objects.filter(
                ad_id__in=sell_incoming
            ).values_list('ad_id', flat=True)
        ) if sell_incoming else set()

        # Rent ads whose ad_id also lives in the sale table are
        # ss.com "sell or rent" dual listings (one tr_ id, one
        # price) — flag them as is_sale_misclassified at ingest.
        sale_twin_ids = set(
            HouseForSale.all_objects.filter(
                ad_id__in=rent_incoming
            ).values_list('ad_id', flat=True)
        ) if rent_incoming else set()
        for r in resources:
            if r['deal_type'] == 'RENT':
                r['sale_listed'] = r['ad_id'] in sale_twin_ids

        if existing_rent_ids:
            self._refresh_sale_flags(existing_rent_ids, sale_twin_ids)
            self._write_sightings(existing_rent_ids, 'RENT')
        if existing_sell_ids:
            self._write_sightings(existing_sell_ids, 'SELL')

        # Self-heal: existing rows whose detail-only fields were never
        # populated (post_date backfill, rooms hardcoded 0 pre-F8)
        # stay in the queue so enrich_result re-fetches the detail
        # page and create_or_update_resources fills them in.
        heal_filter = Q(post_date__isnull=True) | Q(rooms=0)
        heal_ids = set()
        if existing_rent_ids:
            heal_ids |= set(
                HouseForRent.all_objects.filter(
                    heal_filter, ad_id__in=existing_rent_ids,
                ).values_list('ad_id', flat=True)
            )
        if existing_sell_ids:
            heal_ids |= set(
                HouseForSale.all_objects.filter(
                    heal_filter, ad_id__in=existing_sell_ids,
                ).values_list('ad_id', flat=True)
            )

        existing_ids = existing_rent_ids | existing_sell_ids
        kept = []
        for r in resources:
            if r['ad_id'] not in existing_ids:
                kept.append(r)
            elif r['ad_id'] in heal_ids:
                r['_heal'] = True
                kept.append(r)
        return kept

    def _refresh_sale_flags(self, rent_ad_ids, sale_twin_ids):
        """Flag existing rent rows newly detected as for-sale.

        Re-sighted rows bypass create_or_update_resources, so a rent
        ad whose sale twin (or sale-scale price) only appeared after
        the row was created gets its flag updated here. Flagging is
        additive — a row already flagged (e.g. manually in admin) is
        never un-flagged.
        """
        stale = [
            ad for ad in HouseForRent.all_objects.filter(
                ad_id__in=rent_ad_ids,
                is_sale_misclassified=False,
            ).only('ad_id', 'comment', 'monthly_price_per_sqm')
            if ad.ad_id in sale_twin_ids or is_sale_misclassified(
                ad.comment, ad.monthly_price_per_sqm
            )
        ]
        if not stale:
            return
        if self.dry_run:
            logger.info(
                '[dry-run] Would flag %d house rent ad(s) as '
                'is_sale_misclassified.', len(stale),
            )
            return
        for ad in stale:
            ad.is_sale_misclassified = True
        HouseForRent.all_objects.bulk_update(
            stale, ['is_sale_misclassified']
        )
        logger.info(
            'Flagged %d re-sighted house rent ad(s) as '
            'is_sale_misclassified.', len(stale),
        )

    def enrich_result(self, partial_result):
        detail_response = self.make_request(partial_result['link'])
        if detail_response is None:
            # A re-sighted row kept only to heal NULL fields must not
            # overwrite stored values with empty parse defaults —
            # drop it; its sighting was already recorded upstream.
            if partial_result.get('_heal'):
                return None
            return partial_result

        detail = self._parse_detail_page(detail_response)
        return {**partial_result, **detail}

    def _parse_detail_for_refetch(self, response):
        """
        Parse detail page for refetch operation.
        Returns only the fields that can be updated from the detail page.
        """
        detail = self._parse_detail_page(response)

        phone = detail.pop('seller_phone', '')
        contact_id = detail.pop('seller_contact_id', '')

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
            'seller_phone': '',
            'seller_contact_id': '',
        }
        if response is None:
            return result
        # lxml recovers from the unclosed <td>/<tr> tags on this page's
        # attribute table far more reliably than html.parser (same
        # reason as the apartment scraper's detail parser).
        soup = BeautifulSoup(response.data, 'lxml')

        msg_div = soup.find('div', id='msg_div_msg')
        if msg_div:
            for tag in msg_div.find_all(['table', 'div']):
                tag.decompose()
            comment = msg_div.get_text(separator='\n', strip=True)
            if comment:
                result['comment'] = comment

        # Extract post date from msg_footer. ss.com timestamps are
        # Latvia-local; note that post_date is the last-RENEWAL date
        # (renewals bump it) — days-on-market must use sightings/
        # first_seen instead.
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
                    naive = datetime.strptime(
                        raw, '%d.%m.%Y %H:%M'
                    )
                    result['post_date'] = timezone.make_aware(
                        naive, ZoneInfo('Europe/Riga')
                    )
                except (ValueError, TypeError):
                    pass
                break

        # Extract phone number
        prefix_span = soup.find(
            'span', id=re.compile(r'^phone_td_')
        )
        if prefix_span:
            result['seller_phone'] = prefix_span.get_text(strip=True)

        # Extract contact ID from mail link
        mail_link = soup.find(
            'a', href=re.compile(r'/mail/')
        )
        if mail_link:
            href = mail_link.get('href', '')
            result['seller_contact_id'] = (
                href.split('/')[-1].replace('.html', '')
            )

        # ss.com serves this page in whatever language the request's
        # locale path uses (e.g. /lv/ -> "Iela:" instead of "Street:").
        street_raw = self._ads_opt_value(soup, ('Street:', 'Iela:'))
        if street_raw:
            result['street_name'], result['street_no'] = (
                self._split_street(street_raw)
            )

        rooms_raw = self._ads_opt_value(soup, ('Rooms:', 'Istabas:'))
        if rooms_raw:
            try:
                result['rooms'] = int(float(rooms_raw))
            except (ValueError, TypeError):
                pass

        floors_raw = self._ads_opt_value(
            soup, ('Amount of floors:', 'Stāvu skaits:')
        )
        if floors_raw:
            try:
                result['floors'] = int(float(floors_raw))
            except (ValueError, TypeError):
                pass

        land_raw = self._ads_opt_value(
            soup, ('Land area:', 'Zemes platība:')
        )
        if land_raw:
            land_area = _parse_land_area(land_raw)
            if land_area is not None:
                result['land_area_sqm'] = land_area

        house_type = self._ads_opt_value(
            soup, ('House type:', 'Mājas tips:')
        )
        if house_type:
            result['house_type'] = house_type

        return result

    def _ads_opt_value(self, soup, labels):
        """Read one row of the detail page's ads_opt attribute table.

        `labels` is a tuple of accepted label spellings (the page's
        EN/LV variants); returns '' when the row is absent.
        """
        for label_td in soup.find_all('td', class_='ads_opt_name'):
            if label_td.get_text(strip=True) not in labels:
                continue
            value_td = label_td.find_next_sibling(
                'td', class_='ads_opt'
            )
            if not value_td:
                return ''
            bold = value_td.find('b')
            target = bold if bold else value_td
            # Only the tag's own text, not text pulled in from
            # nested/mis-nested tags (e.g. the "[Map]" link).
            return ''.join(
                target.find_all(string=True, recursive=False)
            ).strip()
        return ''

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

        # Junk listings — a token floor area (sheds, garages, land
        # scraps) or a zero computed price-per-m² from an
        # unparseable size — arrive already hidden so the default
        # manager never surfaces them. Same criteria as
        # scripts/quarantine_junk_ads.py.
        is_junk = (
            0 < size_val <= MIN_HOUSE_SIZE_SQM
            or price_per_sqm == 0.0
        )

        deal_type = result['deal_type']
        if deal_type == 'RENT':
            monthly_price = result['total_price']
            monthly_price_per_sqm = price_per_sqm
            total_price_120m = result['alt_price']
            price_per_sqm_120m = (
                total_price_120m / size_val if size_val > 0 else 0.0
            )

            sale_flag = (
                result.get('sale_listed', False)
                or is_sale_misclassified(
                    result['comment'], monthly_price_per_sqm
                )
            )
            rate_period = result.get('rate_period', '')
            room_share = is_room_share(result['comment'])
            if result.get('_heal'):
                # A re-enriched existing row must keep flags set
                # manually or by an earlier scrape — flagging is
                # additive, never undone by re-enrichment.
                stored = HouseForRent.all_objects.filter(
                    ad_id=result['ad_id'],
                ).values_list(
                    'is_sale_misclassified', 'rate_period',
                    'is_room_share',
                ).first()
                if stored:
                    sale_flag = sale_flag or stored[0]
                    if (
                        stored[1] in SHORT_STAY_PERIODS
                        and rate_period not in SHORT_STAY_PERIODS
                    ):
                        rate_period = stored[1]
                    room_share = room_share or stored[2]

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
                house_type=result.get('house_type', ''),
                is_hidden=is_junk,
                is_sale_misclassified=sale_flag,
                rate_period=rate_period,
                is_room_share=room_share,
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
                house_type=result.get('house_type', ''),
                is_hidden=is_junk,
            )

        return None

    def create_or_update_resources(self, resources):
        if not resources:
            return

        rent_ads = [r for r in resources if isinstance(r, HouseForRent)]
        sell_ads = [r for r in resources if isinstance(r, HouseForSale)]

        if self.dry_run:
            logger.info(
                '[dry-run] Would save %d rent ad(s) and %d sale ad(s).',
                len(rent_ads), len(sell_ads),
            )
            return

        if rent_ads:
            HouseForRent.all_objects.bulk_create(
                rent_ads,
                update_conflicts=True,
                unique_fields=['ad_id'],
                update_fields=[
                    'comment', 'link', 'price_per_sqm',
                    'monthly_price', 'monthly_price_per_sqm',
                    'total_price_120m', 'price_per_sqm_120m',
                    'total_price', 'post_date', 'last_seen',
                    'seller', 'is_sale_misclassified',
                    'rooms', 'house_type', 'floors',
                    'land_area_sqm', 'street_name', 'street_no',
                    'rate_period', 'is_room_share',
                ],
            )
            logger.info(f"Saved {len(rent_ads)} rent ads.")
            rent_ids = {ad.ad_id for ad in rent_ads}
            self._write_sightings(rent_ids, 'RENT')

        if sell_ads:
            HouseForSale.all_objects.bulk_create(
                sell_ads,
                update_conflicts=True,
                unique_fields=['ad_id'],
                update_fields=[
                    'comment', 'link', 'price_per_sqm',
                    'total_price', 'post_date', 'last_seen',
                    'seller',
                    'rooms', 'house_type', 'floors',
                    'land_area_sqm', 'street_name', 'street_no',
                ],
            )
            logger.info(f"Saved {len(sell_ads)} sale ads.")
            sell_ids = {ad.ad_id for ad in sell_ads}
            self._write_sightings(sell_ids, 'SELL')

    def _write_sightings(self, ad_ids, deal_type):
        today = date.today()
        if self.dry_run:
            logger.info(
                '[dry-run] Would record %d %s sighting(s) for %s.',
                len(ad_ids), deal_type, today,
            )
            return

        if deal_type == 'RENT':
            existing_ads = HouseForRent.all_objects.filter(
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
            existing_ads = HouseForSale.all_objects.filter(
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

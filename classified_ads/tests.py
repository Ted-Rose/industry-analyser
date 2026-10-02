import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from classified_ads.apartment_scraper import ApartmentAdScraper
from classified_ads.housing_scraper import HousingAdScraper
from classified_ads.models import (
    ApartmentForRent, ApartmentForRentSighting, ApartmentForSale,
    ApartmentForSaleSighting, ApartmentProperty, HouseForRent,
    HouseForRentSighting, HouseProperty, Region, Seller,
)
from classified_ads.property_matcher import (
    extract_apartment_no, match_property, normalize_street_name,
)
from scrape_jobs.models import ScrapeJobRun, ScrapeJobRunItem
from scrape_jobs.runner import ScrapeJobRunner


class ClassifiedAdsApiTests(TestCase):
    """HTTP-layer coverage for the classified_ads SPA API (mounted at
    /api/classified-ads/) and the URL cutover — the retired template
    views' behavior is covered here at the JSON boundary."""

    API = '/api/classified-ads'

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='alice', password='pw'
        )
        self.region = Region.objects.create(
            name='Riga',
            url='https://www.ss.com/en/real-estate/flats/riga/',
            category='APARTMENT',
        )
        self.child = Region.objects.create(
            name='Centrs',
            url='https://www.ss.com/en/real-estate/flats/riga/centre/',
            category='APARTMENT',
            parent=self.region,
        )
        self.house_region = Region.objects.create(
            name='Riga houses',
            url='https://www.ss.com/en/real-estate/'
                'homes-summer-residences/riga/',
            category='HOUSE',
        )
        self._counter = 0

    # --- fixtures ---

    def _rent_ad(self, **kw):
        self._counter += 1
        defaults = dict(
            ad_id=f'rent_{self._counter}',
            link=f'https://example.com/rent/{self._counter}',
            region=self.region,
            district='Centrs',
            street_name='Čaka iela',
            rooms=2,
            size=50.0,
            floor=3,
            max_floor=5,
            price_per_sqm=6.0,
            total_price=300.0,
            monthly_price=300.0,
            monthly_price_per_sqm=6.0,
            total_price_120m=360.0,
            price_per_sqm_120m=7.2,
        )
        defaults.update(kw)
        return ApartmentForRent.all_objects.create(**defaults)

    def _sale_ad(self, **kw):
        self._counter += 1
        defaults = dict(
            ad_id=f'sale_{self._counter}',
            link=f'https://example.com/sale/{self._counter}',
            region=self.region,
            district='Centrs',
            street_name='Čaka iela',
            rooms=2,
            size=50.0,
            floor=3,
            max_floor=5,
            price_per_sqm=2000.0,
            total_price=100000.0,
        )
        defaults.update(kw)
        return ApartmentForSale.all_objects.create(**defaults)

    def _house_rent_ad(self, **kw):
        self._counter += 1
        defaults = dict(
            ad_id=f'hrent_{self._counter}',
            link=f'https://example.com/hrent/{self._counter}',
            region=self.house_region,
            district='Mežaparks',
            street_name='Ezera iela',
            rooms=4,
            size=120.0,
            floors=2,
            price_per_sqm=5.0,
            total_price=600.0,
            monthly_price=600.0,
            monthly_price_per_sqm=5.0,
            total_price_120m=600.0,
            price_per_sqm_120m=5.0,
        )
        defaults.update(kw)
        return HouseForRent.all_objects.create(**defaults)

    # --- URL cutover / shell ---

    def test_index_serves_react_shell(self):
        resp = self.client.get('/classified-ads/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="root"')
        self.assertContains(resp, 'spa-bootstrap')
        self.assertContains(resp, 'Classified Ads')

    def test_deep_link_serves_shell(self):
        for url in (
            '/classified-ads/apartments/rent/',
            '/classified-ads/houses/regions/stats/',
            '/classified-ads/properties/apartments/3/',
            '/classified-ads/daily-sightings/',
        ):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertContains(resp, 'id="root"')

    def test_non_get_to_spa_urls_404s(self):
        for url in (
            '/classified-ads/',
            '/classified-ads/apartments/rent/',
        ):
            for method in ('post', 'put', 'delete'):
                resp = getattr(self.client, method)(url)
                self.assertEqual(
                    resp.status_code, 404, f'{method} {url}'
                )

    def test_named_routes_still_reverse(self):
        self.assertEqual(
            reverse('classified_ads:index'), '/classified-ads/'
        )
        self.assertEqual(
            reverse('classified_ads:apartment_rent_ads_table'),
            '/classified-ads/apartments/rent/',
        )
        self.assertEqual(
            reverse('classified_ads:house_region_stats_children',
                    kwargs={'region_id': 7}),
            '/classified-ads/houses/regions/stats/7/children/',
        )
        self.assertEqual(
            reverse('classified_ads:apartment_property_detail',
                    kwargs={'pk': 3}),
            '/classified-ads/properties/apartments/3/',
        )
        self.assertEqual(
            reverse('classified_ads:daily_sightings_report'),
            '/classified-ads/daily-sightings/',
        )

    # --- GET /api/classified-ads/ads/ ---

    def test_ads_table_is_public(self):
        ad = self._rent_ad()
        resp = self.client.get(
            f'{self.API}/ads/',
            {'kind': 'apartment', 'deal': 'rent'},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        row = body['ads'][0]
        self.assertEqual(row['ad_id'], ad.ad_id)
        self.assertEqual(row['deal'], 'Rent')
        self.assertEqual(row['monthly_price'], 300.0)
        self.assertIn('districts', body)
        self.assertIn('room_choices', body)

    def test_ads_table_hidden_and_misclassified_excluded(self):
        self._rent_ad()
        self._rent_ad(is_hidden=True)
        self._rent_ad(is_sale_misclassified=True)
        resp = self.client.get(
            f'{self.API}/ads/',
            {'kind': 'apartment', 'deal': 'rent'},
        )
        self.assertEqual(resp.json()['total_count'], 1)

    def test_ads_table_filters(self):
        kept = self._rent_ad(
            district='Āgenskalns', rooms=3, monthly_price_per_sqm=9.0
        )
        self._rent_ad()
        resp = self.client.get(
            f'{self.API}/ads/',
            {
                'kind': 'apartment', 'deal': 'rent',
                'district': 'Āgenskalns', 'rooms': '3',
                'price_min': '8', 'price_max': '10',
            },
        )
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(body['ads'][0]['ad_id'], kept.ad_id)
        self.assertEqual(body['filters']['district'], 'Āgenskalns')
        self.assertEqual(body['filters']['rooms'], 3)
        # Rent tables filter on monthly_price_per_sqm — 7 keeps only
        # the 6.0 ad, not the 9.0 one.
        resp = self.client.get(
            f'{self.API}/ads/',
            {'kind': 'apartment', 'deal': 'rent', 'price_max': '7'},
        )
        self.assertEqual(resp.json()['total_count'], 1)
        resp = self.client.get(
            f'{self.API}/ads/',
            {'kind': 'apartment', 'deal': 'rent', 'price_max': '5'},
        )
        self.assertEqual(resp.json()['total_count'], 0)

    def test_ads_table_sale_uses_price_per_sqm(self):
        self._sale_ad(price_per_sqm=2000.0)
        self._sale_ad(price_per_sqm=500.0)
        resp = self.client.get(
            f'{self.API}/ads/',
            {'kind': 'apartment', 'deal': 'sale',
             'price_min': '1000'},
        )
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(body['ads'][0]['deal'], 'Sell')
        self.assertIsNone(body['ads'][0]['monthly_price'])

    def test_ads_table_house_kind(self):
        ad = self._house_rent_ad()
        resp = self.client.get(
            f'{self.API}/ads/', {'kind': 'house', 'deal': 'rent'}
        )
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(body['ads'][0]['ad_id'], ad.ad_id)
        self.assertEqual(body['ads'][0]['floors'], 2)

    def test_ads_table_pagination(self):
        self._rent_ad()
        self._rent_ad()
        with mock.patch('classified_ads.api.ADS_PER_PAGE', 1):
            first = self.client.get(
                f'{self.API}/ads/',
                {'kind': 'apartment', 'deal': 'rent', 'page': 1},
            )
            second = self.client.get(
                f'{self.API}/ads/',
                {'kind': 'apartment', 'deal': 'rent', 'page': 2},
            )
        body = first.json()
        self.assertEqual(body['num_pages'], 2)
        self.assertTrue(body['has_next'])
        self.assertFalse(body['has_previous'])
        self.assertTrue(second.json()['has_previous'])

    def test_ads_table_bad_kind_422s(self):
        resp = self.client.get(
            f'{self.API}/ads/', {'kind': 'yacht', 'deal': 'rent'}
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()['error'], 'validation_error')

    # --- GET /api/classified-ads/regions/config/ + POST ---

    def test_region_config_get_is_public(self):
        self.region.scrape_enabled = True
        self.region.save()
        resp = self.client.get(
            f'{self.API}/regions/config/', {'kind': 'apartment'}
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['kind'], 'apartment')
        self.assertEqual(body['total_count'], 2)  # region + child
        self.assertEqual(body['enabled_count'], 1)
        tree = body['regions_tree']
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]['sub_regions'][0]['name'], 'Centrs')

    def test_region_config_get_house_set(self):
        resp = self.client.get(
            f'{self.API}/regions/config/', {'kind': 'house'}
        )
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(
            body['regions_tree'][0]['name'], 'Riga houses'
        )

    def test_region_config_post_unauthenticated_401(self):
        resp = self.client.post(
            f'{self.API}/regions/config/',
            data=json.dumps(
                {'kind': 'apartment', 'regions': [self.region.url]}
            ),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)
        body = resp.json()
        self.assertEqual(body['error'], 'unauthenticated')
        self.assertIn(
            'next=%2Fclassified-ads%2Fregions%2Fconfig%2F',
            body['login_url'],
        )

    def test_region_config_post_success(self):
        self.child.scrape_enabled = True
        self.child.save()
        self.house_region.scrape_enabled = True
        self.house_region.save()
        self.client.force_login(self.user)
        resp = self.client.post(
            f'{self.API}/regions/config/',
            data=json.dumps(
                {'kind': 'apartment', 'regions': [self.region.url]}
            ),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'success': True,
             'message': 'Region configuration saved.'},
        )
        self.region.refresh_from_db()
        self.child.refresh_from_db()
        self.house_region.refresh_from_db()
        self.assertTrue(self.region.scrape_enabled)
        # Unchecked apartment regions are disabled wholesale.
        self.assertFalse(self.child.scrape_enabled)
        # The house set is untouched by an apartment POST.
        self.assertTrue(self.house_region.scrape_enabled)

    def test_region_config_post_csrf_enforced(self):
        csrf_client = self.client.__class__(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        resp = csrf_client.post(
            f'{self.API}/regions/config/',
            data=json.dumps({'kind': 'apartment', 'regions': []}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error'], 'forbidden')

    # --- GET /api/classified-ads/regions/stats/ ---

    def test_region_stats_is_public(self):
        self._rent_ad()
        resp = self.client.get(
            f'{self.API}/regions/stats/',
            {'kind': 'apartment', 'deal_type': 'RENT',
             'regions': [str(self.region.id)]},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['selected_ids'], [self.region.id])
        self.assertEqual(len(body['results']), 1)
        row = body['results'][0]
        self.assertEqual(row['region']['name'], 'Riga')
        self.assertEqual(row['total_ads'], 1)

    def test_region_stats_null_without_selection(self):
        resp = self.client.get(
            f'{self.API}/regions/stats/', {'kind': 'house'}
        )
        body = resp.json()
        self.assertIsNone(body['results'])
        # Only HOUSE-category parents are offered.
        self.assertEqual(
            [r['name'] for r in body['parent_regions']],
            ['Riga houses'],
        )

    def test_region_stats_children(self):
        self._rent_ad(region=self.child)
        resp = self.client.get(
            f'{self.API}/regions/{self.region.id}/children/',
            {'kind': 'apartment', 'deal_type': 'RENT'},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['parent_region']['name'], 'Riga')
        self.assertEqual(len(body['results']), 1)
        self.assertEqual(body['results'][0]['total_ads'], 1)

    def test_region_stats_children_404s_non_parent(self):
        resp = self.client.get(
            f'{self.API}/regions/{self.child.id}/children/',
            {'kind': 'apartment'},
        )
        self.assertEqual(resp.status_code, 404)

    # --- GET /api/classified-ads/regions/{id}/ads/ ---

    def test_region_ads_list(self):
        ad = self._rent_ad(region=self.child)
        resp = self.client.get(
            f'{self.API}/regions/{self.region.id}/ads/',
            {'kind': 'apartment', 'deal_type': 'RENT'},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # Descendant regions are included.
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(body['ads'][0]['ad_id'], ad.ad_id)

    def test_region_ads_list_blank_deal_type_is_empty(self):
        self._rent_ad(region=self.region)
        resp = self.client.get(
            f'{self.API}/regions/{self.region.id}/ads/',
            {'kind': 'apartment'},
        )
        self.assertEqual(resp.json()['total_count'], 0)

    # --- GET /api/classified-ads/sightings/ ---

    def test_daily_sightings_report(self):
        rent = self._rent_ad()
        sale = self._sale_ad()
        house = self._house_rent_ad()
        today = date.today()
        ApartmentForRentSighting.objects.create(
            ad=rent, seen_on=today
        )
        ApartmentForSaleSighting.objects.create(
            ad=sale, seen_on=today
        )
        HouseForRentSighting.objects.create(ad=house, seen_on=today)
        resp = self.client.get(
            f'{self.API}/sightings/',
            {'date_from': today.isoformat(),
             'date_to': today.isoformat()},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body['daily_data']), 1)
        row = body['daily_data'][0]
        self.assertEqual(row['apartment_rent'], 1)
        self.assertEqual(row['apartment_sale'], 1)
        self.assertEqual(row['house_rent'], 1)
        self.assertEqual(row['house_sale'], 0)
        self.assertEqual(row['grand_total'], 3)

    def test_daily_sightings_region_filter(self):
        rent = self._rent_ad(region=self.child)
        house = self._house_rent_ad()
        today = date.today()
        ApartmentForRentSighting.objects.create(
            ad=rent, seen_on=today
        )
        HouseForRentSighting.objects.create(ad=house, seen_on=today)
        resp = self.client.get(
            f'{self.API}/sightings/',
            {'region': str(self.region.id)},
        )
        row = resp.json()['daily_data'][0]
        # The parent's subtree includes the child's sighting but not
        # the house region's.
        self.assertEqual(row['apartment_rent'], 1)
        self.assertEqual(row['house_rent'], 0)
        self.assertEqual(
            resp.json()['selected_region'], self.region.id
        )

    def test_daily_sightings_unknown_region_404s(self):
        resp = self.client.get(
            f'{self.API}/sightings/', {'region': '99999'}
        )
        self.assertEqual(resp.status_code, 404)

    # --- GET /api/classified-ads/properties/ ---

    def _property_with_ad(self):
        ad = self._rent_ad()
        prop = ApartmentProperty.from_ad(ad)
        prop.save()
        ad.property = prop
        ad.property_match_status = 'auto'
        ad.property_match_score = 0.9
        ad.save()
        return prop, ad

    def test_property_list_is_public(self):
        prop, ad = self._property_with_ad()
        resp = self.client.get(
            f'{self.API}/properties/', {'kind': 'apartment'}
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        row = body['properties'][0]
        self.assertEqual(row['id'], prop.pk)
        self.assertEqual(row['rent_ad_count'], 1)
        self.assertEqual(row['sale_ad_count'], 0)
        self.assertEqual(body['kind_label'], 'Apartment')

    def test_property_list_filters(self):
        prop, _ = self._property_with_ad()
        ad = self._rent_ad(district='Āgenskalns')
        prop2 = ApartmentProperty.from_ad(ad)
        prop2.save()
        resp = self.client.get(
            f'{self.API}/properties/',
            {'kind': 'apartment', 'district': 'Āgenskalns'},
        )
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(body['properties'][0]['id'], prop2.pk)
        resp = self.client.get(
            f'{self.API}/properties/',
            {'kind': 'apartment', 'street': 'nomatch'},
        )
        self.assertEqual(resp.json()['total_count'], 0)

    def test_property_detail_is_public(self):
        prop, ad = self._property_with_ad()
        ApartmentForRentSighting.objects.create(
            ad=ad, seen_on=date.today()
        )
        resp = self.client.get(
            f'{self.API}/properties/apartment/{prop.pk}/'
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['id'], prop.pk)
        self.assertEqual(body['street_name'], 'Čaka iela')
        self.assertEqual(body['days_on_market'], 1)
        self.assertEqual(len(body['ad_rows']), 1)
        row = body['ad_rows'][0]
        self.assertEqual(row['ad_id'], ad.ad_id)
        self.assertEqual(row['deal'], 'Rent')
        self.assertEqual(row['price_suffix'], '/mo')

    def test_property_detail_includes_hidden_ads(self):
        """linked_ads() uses all_objects — hidden ads still belong."""
        prop, _ = self._property_with_ad()
        hidden = self._rent_ad(is_hidden=True)
        hidden.property = prop
        hidden.property_match_status = 'auto'
        hidden.save()
        resp = self.client.get(
            f'{self.API}/properties/apartment/{prop.pk}/'
        )
        self.assertEqual(len(resp.json()['ad_rows']), 2)

    def test_property_detail_404_and_bad_kind(self):
        resp = self.client.get(
            f'{self.API}/properties/apartment/99999/'
        )
        self.assertEqual(resp.status_code, 404)
        resp = self.client.get(f'{self.API}/properties/yacht/1/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'bad_request')

    def test_house_property_list(self):
        HouseProperty.objects.create(
            district='Mežaparks',
            street_name='Ezera iela',
            street_no='1',
            rooms=4,
            size=120.0,
            floors=2,
            first_seen=timezone.now(),
            last_seen=timezone.now(),
        )
        resp = self.client.get(
            f'{self.API}/properties/', {'kind': 'house'}
        )
        body = resp.json()
        self.assertEqual(body['kind_label'], 'House')
        self.assertEqual(body['total_count'], 1)


class ApartmentAdScraperRunnerTest(TestCase):
    """get_search_urls() wired onto ScrapeJobRunner (plan PR-2)."""

    def setUp(self):
        self.riga = Region.objects.create(
            name='Riga',
            url='https://www.ss.com/en/real-estate/flats/riga/',
            scrape_enabled=True,
            order_id='2',
        )
        self.jurmala = Region.objects.create(
            name='Jurmala',
            url='https://www.ss.com/en/real-estate/flats/jurmala/',
            scrape_enabled=True,
            order_id='n/a',
        )
        Region.objects.create(
            name='Off',
            url='https://www.ss.com/en/real-estate/flats/off/',
            scrape_enabled=False,
        )

    def test_full_pass_without_runner(self):
        scraper = ApartmentAdScraper(max_pages=2)
        urls = list(scraper.get_search_urls())
        # 2 enabled regions x 2 deal types x 2 pages, id order
        self.assertEqual(len(urls), 8)
        self.assertEqual(urls[0], self.riga.url + 'hand_over/')
        self.assertEqual(
            urls[-1], self.jurmala.url + 'sell/page2.html'
        )

    def test_runner_failure_isolation(self):
        runner = ScrapeJobRunner(
            slug='classified_ads.apartment_ads',
            cycle_key='2024-01-01',
            fresh=True,
        )
        scraper = ApartmentAdScraper(max_pages=1, runner=runner)
        urls = iter(scraper.get_search_urls())
        # Highest priority first ('2' beats unparseable 'n/a' -> 0)
        self.assertEqual(next(urls), self.riga.url + 'hand_over/')
        # run() throws scrape_portal() failures back into the
        # generator — the item is marked FAILED and the next
        # region's first URL is yielded.
        self.assertEqual(
            urls.throw(RuntimeError('boom')),
            self.jurmala.url + 'hand_over/',
        )
        self.assertEqual(next(urls), self.jurmala.url + 'sell/')
        self.assertRaises(StopIteration, next, urls)

        run_items = ScrapeJobRunItem.objects.filter(run=runner.run)
        self.assertEqual(
            run_items.get(item__key=str(self.riga.id)).status,
            ScrapeJobRunItem.FAILED,
        )
        self.assertEqual(
            run_items.get(item__key=str(self.jurmala.id)).status,
            ScrapeJobRunItem.DONE,
        )
        runner.finish()
        runner.run.refresh_from_db()
        self.assertEqual(runner.run.status, ScrapeJobRun.PARTIAL)

    def test_resume_skips_completed_items(self):
        runner1 = ScrapeJobRunner(
            slug='classified_ads.apartment_ads',
            cycle_key='2024-01-02',
            fresh=True,
        )
        scraper = ApartmentAdScraper(max_pages=1, runner=runner1)
        urls = iter(scraper.get_search_urls())
        next(urls)  # Riga hand_over
        next(urls)  # Riga sell — last URL of the item
        # Resuming past that yield fires item_done(Riga), then
        # Jurmala's first URL comes out.
        self.assertEqual(
            next(urls), self.jurmala.url + 'hand_over/'
        )
        self.assertTrue(
            ScrapeJobRunItem.objects.filter(
                run=runner1.run,
                item__key=str(self.riga.id),
                status=ScrapeJobRunItem.DONE,
            ).exists()
        )
        # runner1 stays RUNNING — simulating an interrupted run.

        runner2 = ScrapeJobRunner(
            slug='classified_ads.apartment_ads',
            cycle_key='2024-01-02',
        )
        self.assertIn(str(self.riga.id), runner2.completed_keys)
        scraper2 = ApartmentAdScraper(max_pages=1, runner=runner2)
        urls2 = list(scraper2.get_search_urls())
        self.assertNotIn(self.riga.url + 'hand_over/', urls2)
        self.assertEqual(urls2[0], self.jurmala.url + 'hand_over/')
        runner2.finish()

    def test_dry_run_writes_nothing(self):
        scraper = ApartmentAdScraper(dry_run=True)
        ad = ApartmentForRent(
            ad_id='tr_dry', link='https://example.com/x',
            region=self.riga,
        )
        scraper.create_or_update_resources([ad])
        self.assertEqual(ApartmentForRent.all_objects.count(), 0)
        scraper._write_sightings({'tr_dry'}, 'RENT')
        self.assertEqual(ApartmentForRentSighting.objects.count(), 0)


class HousingAdScraperRunnerTest(TestCase):
    def test_only_housing_regions_become_items(self):
        Region.objects.create(
            name='Flat region',
            url='https://www.ss.com/en/real-estate/flats/riga/',
            scrape_enabled=True,
        )
        house = Region.objects.create(
            name='House region',
            url='https://www.ss.com/en/real-estate/'
                'homes-summer-residences/riga/',
            scrape_enabled=True,
        )
        runner = ScrapeJobRunner(
            slug='classified_ads.house_ads', dry_run=True,
        )
        scraper = HousingAdScraper(
            max_pages=1, runner=runner, dry_run=True,
        )
        urls = list(scraper.get_search_urls())
        self.assertEqual(
            urls,
            [house.url + 'hand_over/', house.url + 'sell/'],
        )


class PaginationEndDetectionTest(TestCase):
    """ss.com redirects out-of-range pageN.html listing URLs back to
    the first page — pagination must stop instead of re-scraping the
    same listing until max_pages."""

    APARTMENT_ROW = (
        '<tr id="tr_1"><td></td>'
        '<td><a href="/msg/en/x.html">x</a></td><td>note</td>'
        '<td>Street 1</td><td>2</td><td>50</td><td>3/5</td>'
        '<td>New</td><td>10</td><td>500</td></tr>'
    )

    @staticmethod
    def _response(html=b'', redirect_location=None):
        history = ()
        if redirect_location:
            history = (
                SimpleNamespace(redirect_location=redirect_location),
            )
        return SimpleNamespace(
            data=html,
            retries=SimpleNamespace(history=history),
            geturl=lambda: 'https://www.ss.com/lv/final/',
        )

    def test_run_stops_when_page_redirects(self):
        region = Region.objects.create(
            name='Riga houses',
            url='https://www.ss.com/en/real-estate/'
                'homes-summer-residences/riga/',
            scrape_enabled=True,
        )
        scraper = HousingAdScraper(max_pages=10)
        redirected = self._response(redirect_location='/some/')
        requested = []

        def fake_request(url, **kw):
            requested.append(url)
            return redirected

        scraper.make_request = fake_request
        scraper.run()
        # Each deal type stops after its first page despite
        # max_pages=10 — no page2.html..page10.html fetches.
        self.assertEqual(
            requested,
            [region.url + 'hand_over/', region.url + 'sell/'],
        )

    def test_repeated_page_stops_pagination(self):
        scraper = ApartmentAdScraper(max_pages=10)
        scraper._current_region = Region(name='Riga', url='https://x/')
        scraper._current_deal_type = 'SELL'
        html = f'<table>{self.APARTMENT_ROW}</table>'.encode()
        scraper.make_request = lambda url, **kw: self._response(html)

        scraper.scrape_portal('https://x/hand_over/')
        self.assertTrue(scraper.last_search_had_results)
        # Same ad ids served again (repeated last/first page):
        # scrape_portal reports no results so pagination stops.
        scraper.scrape_portal('https://x/hand_over/page2.html')
        self.assertFalse(scraper.last_search_had_results)

    def test_distinct_pages_keep_paginating(self):
        scraper = ApartmentAdScraper(max_pages=10)
        scraper._current_region = Region(name='Riga', url='https://x/')
        scraper._current_deal_type = 'SELL'
        html1 = f'<table>{self.APARTMENT_ROW}</table>'.encode()
        html2 = (
            '<table>' + self.APARTMENT_ROW.replace('tr_1', 'tr_2')
            + '</table>'
        ).encode()
        self.assertEqual(
            len(scraper.parse_results(self._response(html1))), 1
        )
        self.assertEqual(
            len(scraper.parse_results(self._response(html2))), 1
        )


class StreetNameNormalizationTest(TestCase):
    def test_strips_designators_and_initials(self):
        self.assertEqual(
            normalize_street_name('A. Čaka iela'), 'čaka'
        )
        self.assertEqual(normalize_street_name('Čaka'), 'čaka')
        self.assertEqual(
            normalize_street_name('Brīvības bulvāris'), 'brīvības'
        )
        self.assertEqual(
            normalize_street_name('  Bruņinieku   Iela '), 'bruņinieku'
        )

    def test_extract_apartment_no(self):
        self.assertEqual(
            extract_apartment_no('Pārdod. Dzīvoklis Nr. 49'), '49'
        )
        self.assertEqual(
            extract_apartment_no('Dzīvokļa numurs 7, labs'), '7'
        )
        self.assertEqual(extract_apartment_no('No number here'), '')
        # Bare number after "dzīvoklis" is a floor/room count, not a
        # unit number — only marker words count.
        self.assertEqual(
            extract_apartment_no('Dzīvoklis 3. stāvā'), ''
        )


class PropertyMatcherTest(TestCase):
    def setUp(self):
        self.seller = Seller.objects.create(phone='111', contact_id='c1')
        self.other_seller = Seller.objects.create(phone='222')
        self._counter = 0

    def _rent_ad(self, **kw):
        self._counter += 1
        defaults = dict(
            ad_id=f'rent_{self._counter}',
            comment='',
            link=f'https://example.com/rent/{self._counter}',
            district='Centrs',
            street_name='Čaka iela',
            street_no='133',
            rooms=2,
            size=50.0,
            floor=3,
            max_floor=5,
            price_per_sqm=6.0,
            total_price=300.0,
            monthly_price=300.0,
            monthly_price_per_sqm=6.0,
            total_price_120m=360.0,
            price_per_sqm_120m=7.2,
            seller=self.seller,
        )
        defaults.update(kw)
        return ApartmentForRent.all_objects.create(**defaults)

    def _sale_ad(self, **kw):
        self._counter += 1
        defaults = dict(
            ad_id=f'sale_{self._counter}',
            comment='',
            link=f'https://example.com/sale/{self._counter}',
            district='Centrs',
            street_name='Čaka iela',
            street_no='133',
            rooms=2,
            size=50.0,
            floor=3,
            max_floor=5,
            price_per_sqm=2000.0,
            total_price=100000.0,
            seller=self.seller,
        )
        defaults.update(kw)
        return ApartmentForSale.all_objects.create(**defaults)

    def _property_from(self, ad):
        prop = ApartmentProperty.from_ad(ad)
        prop.save()
        prop._linked_ads_cache = [ad]
        ad.property = prop
        ad.property_match_status = 'auto'
        ad.save()
        return prop

    def test_repost_chain_auto_links(self):
        ad1 = self._rent_ad(comment='Jauks dzīvoklis centrā, lifti')
        prop = self._property_from(ad1)

        ad2 = self._rent_ad(comment='Jauks dzīvoklis centrā, lifti')
        best, score, decision = match_property(ad2, [prop])

        self.assertEqual(decision, 'auto')
        self.assertIs(best, prop)
        self.assertGreaterEqual(score, 0.8)

    def test_different_flat_numbers_stay_split(self):
        """Chaka-133 case: identical fingerprints, different units."""
        ad1 = self._rent_ad(
            comment='Pārdod. Dzīvoklis Nr. 56, jauns remonts'
        )
        prop = self._property_from(ad1)

        ad2 = self._rent_ad(
            seller=self.other_seller,
            comment='Dzīvoklis Nr. 49, cita māja',
        )
        best, score, decision = match_property(ad2, [prop])

        self.assertEqual(decision, 'new')
        self.assertIsNone(best)

    def test_rent_and_sale_ads_share_property(self):
        rent_ad = self._rent_ad(comment='Same unit, rented first')
        prop = self._property_from(rent_ad)

        sale_ad = self._sale_ad(comment='Same unit, rented first')
        best, score, decision = match_property(sale_ad, [prop])

        self.assertEqual(decision, 'auto')
        self.assertIs(best, prop)

    def test_mid_score_goes_to_review(self):
        ad1 = self._rent_ad()
        prop = self._property_from(ad1)

        # Same seller + floor + max_floor + temporal adjacency, size
        # off by 4%, no comment match: score ~0.68 → review band.
        ad2 = self._rent_ad(size=48.0)
        best, score, decision = match_property(ad2, [prop])

        self.assertEqual(decision, 'candidate')
        self.assertIs(best, prop)
        self.assertGreaterEqual(score, 0.45)
        self.assertLess(score, 0.8)

    def test_rooms_conflict_is_hard_reject(self):
        ad1 = self._rent_ad()
        prop = self._property_from(ad1)

        ad2 = self._rent_ad(rooms=3)
        best, score, decision = match_property(ad2, [prop])

        self.assertEqual(decision, 'new')
        self.assertIsNone(best)

    def test_street_name_variants_match(self):
        ad1 = self._rent_ad(street_name='A. Čaka iela')
        prop = self._property_from(ad1)

        ad2 = self._rent_ad(street_name='Čaka')
        best, score, decision = match_property(ad2, [prop])

        self.assertEqual(decision, 'auto')
        self.assertIs(best, prop)


class LinkAdsToPropertiesCommandTest(TestCase):
    def _rent_ad(self, ad_id, **kw):
        defaults = dict(
            ad_id=ad_id,
            comment='Same flat, reposted',
            link=f'https://example.com/{ad_id}',
            district='Centrs',
            street_name='Čaka iela',
            street_no='133',
            rooms=2,
            size=50.0,
            floor=3,
            max_floor=5,
            price_per_sqm=6.0,
            total_price=300.0,
            monthly_price=300.0,
            monthly_price_per_sqm=6.0,
            total_price_120m=360.0,
            price_per_sqm_120m=7.2,
        )
        defaults.update(kw)
        return ApartmentForRent.all_objects.create(**defaults)

    def test_links_repost_chain_and_is_idempotent(self):
        seller = Seller.objects.create(phone='111')
        ad1 = self._rent_ad('a1', seller=seller)
        ad2 = self._rent_ad('a2', seller=seller)

        call_command(
            'link_ads_to_properties',
            '--type', 'apartment', '--deal', 'rent',
        )

        ad1.refresh_from_db()
        ad2.refresh_from_db()
        self.assertIsNotNone(ad1.property_id)
        self.assertEqual(ad1.property_id, ad2.property_id)
        self.assertEqual(ad1.property_match_status, 'auto')
        self.assertEqual(ad2.property_match_status, 'auto')
        self.assertEqual(ApartmentProperty.objects.count(), 1)

        # Second run processes nothing — idempotent.
        call_command(
            'link_ads_to_properties',
            '--type', 'apartment', '--deal', 'rent',
        )
        self.assertEqual(ApartmentProperty.objects.count(), 1)

    def test_dry_run_writes_nothing(self):
        from io import StringIO

        seller = Seller.objects.create(phone='111')
        self._rent_ad('a1', seller=seller)
        self._rent_ad('a2', seller=seller)
        out = StringIO()
        call_command(
            'link_ads_to_properties',
            '--type', 'apartment', '--deal', 'rent', '--dry-run',
            stdout=out,
        )
        # In-memory properties still chain in dry-run: 1 new + 1 link.
        self.assertIn('New properties:    1', out.getvalue())
        self.assertIn('Auto-linked:       1', out.getvalue())
        self.assertEqual(ApartmentProperty.objects.count(), 0)
        self.assertEqual(
            ApartmentForRent.all_objects.filter(
                property_match_status='unmatched'
            ).count(),
            2,
        )

    def test_older_than_days_skips_recent_ads(self):
        seller = Seller.objects.create(phone='111')
        old_ad = self._rent_ad('old', seller=seller)
        new_ad = self._rent_ad('new', seller=seller)
        # first_seen is auto_now_add — backdate via UPDATE.
        ApartmentForRent.all_objects.filter(pk=old_ad.pk).update(
            first_seen=timezone.now() - timedelta(days=10)
        )

        call_command(
            'link_ads_to_properties',
            '--type', 'apartment', '--deal', 'rent',
            '--older-than-days', '3',
        )

        old_ad.refresh_from_db()
        new_ad.refresh_from_db()
        self.assertEqual(old_ad.property_match_status, 'auto')
        self.assertIsNotNone(old_ad.property_id)
        self.assertEqual(new_ad.property_match_status, 'unmatched')
        self.assertIsNone(new_ad.property_id)

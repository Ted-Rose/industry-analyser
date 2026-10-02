from datetime import date, timedelta
from types import SimpleNamespace

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from classified_ads.apartment_scraper import ApartmentAdScraper
from classified_ads.housing_scraper import HousingAdScraper
from classified_ads.models import (
    ApartmentForRent, ApartmentForRentSighting, ApartmentForSale,
    ApartmentProperty, Region, Seller,
)
from classified_ads.property_matcher import (
    extract_apartment_no, match_property, normalize_street_name,
)
from scrape_jobs.models import ScrapeJobRun, ScrapeJobRunItem
from scrape_jobs.runner import ScrapeJobRunner


class DailySightingsReportViewTest(TestCase):
    def test_daily_sightings_report_loads(self):
        url = reverse('classified_ads:daily_sightings_report')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Daily Sightings Report')

    def test_daily_sightings_with_date_range(self):
        date_from = (date.today() - timedelta(days=7)).isoformat()
        date_to = date.today().isoformat()
        url = reverse('classified_ads:daily_sightings_report')
        response = self.client.get(
            url,
            {'date_from': date_from, 'date_to': date_to}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, date_from)
        self.assertContains(response, date_to)


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

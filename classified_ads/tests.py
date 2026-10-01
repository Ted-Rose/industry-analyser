from datetime import date, timedelta
from django.test import TestCase
from django.urls import reverse

from classified_ads.apartment_scraper import ApartmentAdScraper
from classified_ads.housing_scraper import HousingAdScraper
from classified_ads.models import (
    ApartmentForRent, ApartmentForRentSighting, Region,
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

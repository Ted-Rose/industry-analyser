import datetime
import pathlib
from types import SimpleNamespace
from unittest import skipIf

from django.test import TestCase
from django.utils import timezone

from scrape_jobs.models import ScrapeJobRunItem
from scrape_jobs.runner import ScrapeJobRunner
from tv_programs.classification import EXCLUDED_LOCAL_SHOWS, classify
from tv_programs.models import Channel, Program
from tv_programs.scraper import TVProgramScraper

_FIXTURE = pathlib.Path(__file__).parent / "tests" / "fixtures" / "tet_sample.html"
_HAS_FIXTURE = _FIXTURE.is_file()


@skipIf(not _HAS_FIXTURE, "tet sample fixture not present at tv_programs/tests/fixtures/")
class ParserIntegrationTests(TestCase):
    def setUp(self):
        self.data = _FIXTURE.read_bytes()
        self.scraper = TVProgramScraper()
        self.scraper.current_channel, _ = Channel.objects.get_or_create(
            name="ltv1_hd"
        )
        self.scraper.current_start_time = timezone.make_aware(
            datetime.datetime(2026, 4, 24, 0, 0, 0),
            datetime.timezone.utc,
        )

    def test_parse_sets_classification(self):
        resp = SimpleNamespace(data=self.data)
        out = self.scraper.parse_results(resp)
        self.assertEqual(len(out), 3, out)
        for p in out:
            c = p["classification"]
            self.assertTrue(0.0 <= c.confidence <= 1.0)
            self.assertIn(c.content_type, ("movie", "not_movie", "unknown"))


class ClassifyHeuristicTests(TestCase):
    def test_title_filma(self):
        c = classify("Mana filma. Drāma", "", "ltv1_hd", 90)
        self.assertEqual(c.content_type, "movie")
        self.assertGreaterEqual(c.confidence, 0.99)

    def test_series_in_title(self):
        c = classify("Detektīvseriāls. 1. sērija", "test", "ltv1_hd", 60)
        self.assertEqual(c.content_type, "not_movie")

    def test_markers_in_description(self):
        c = classify("Nosaukums", "Tas ir seriāls", "ltv1_hd", 120)
        self.assertEqual(c.content_type, "not_movie")

    def test_filmzone_60_mins(self):
        c = classify("Bez sērijām", "nav", "filmzone_hd", 60)
        self.assertEqual(c.content_type, "movie")

    def test_ltv_90_mins(self):
        c = classify("Bez sērijām", "", "ltv1_hd", 90)
        self.assertEqual(c.content_type, "movie")

    def test_short_block(self):
        c = classify("Kaut kas", "", "ltv1_hd", 30)
        self.assertEqual(c.content_type, "not_movie")

    def test_ambiguous_50_on_general_channel(self):
        c = classify("Nosaukums", "", "ltv1_hd", 50)
        self.assertEqual(c.content_type, "unknown")


class ExclusionListTest(TestCase):
    def test_plan_titles_merged(self):
        self.assertIn("Kas notiek Latvijā?", EXCLUDED_LOCAL_SHOWS)
        self.assertIn("Panorāma", EXCLUDED_LOCAL_SHOWS)


class GetSearchUrlsRunnerTests(TestCase):
    """scrape_jobs runner wiring: one item per channel x date cell,
    oldest days first; items are checkpointed as the urls yield."""

    CONFIG = {"days_in_past": 1, "days_in_future": 1}

    def test_items_are_channel_x_date_oldest_first(self):
        runner = ScrapeJobRunner(
            slug="tv_programs.guide",
            cycle_key="2026-01-01",
            fresh=True,
        )
        scraper = TVProgramScraper(config=self.CONFIG, runner=runner)

        urls = list(scraper.get_search_urls())

        # 2 days x 3 channels; the oldest day's channels come first.
        self.assertEqual(len(urls), 6)
        yesterday = (timezone.now() - datetime.timedelta(days=1))
        today = timezone.now()
        self.assertIn(
            f"date={yesterday.strftime('%Y-%m-%d')}", urls[0]
        )
        self.assertIn("channel=filmzone_hd", urls[0])
        self.assertIn(f"date={today.strftime('%Y-%m-%d')}", urls[3])
        # Scraper context follows the item being yielded.
        self.assertEqual(scraper.current_channel.name, "ltv1_hd")
        self.assertEqual(
            ScrapeJobRunItem.objects.filter(
                run=runner.run, status=ScrapeJobRunItem.DONE
            ).count(),
            6,
        )

    def test_dry_run_writes_no_channel_rows(self):
        runner = ScrapeJobRunner(
            slug="tv_programs.guide",
            cycle_key="2026-01-02",
            dry_run=True,
        )
        scraper = TVProgramScraper(
            config=self.CONFIG, runner=runner, dry_run=True
        )

        urls = list(scraper.get_search_urls())

        self.assertEqual(len(urls), 6)
        self.assertEqual(Channel.objects.count(), 0)
        self.assertEqual(scraper.current_channel.name, "ltv1_hd")
        self.assertIsNone(scraper.current_channel.pk)


class ReclassifyCommandDataTests(TestCase):
    def test_reclassify_updates_row(self):
        ch, _ = Channel.objects.get_or_create(name="ltv1_hd")
        st = timezone.now()
        p = Program.objects.create(
            title_lv="Dienas ziņas. Raidījums",
            title_eng=None,
            description_lv="",
            channel=ch,
            start_time=st,
            duration_minutes=25,
        )
        from io import StringIO
        from django.core.management import call_command

        out = StringIO()
        call_command("reclassify_tv_programs", stdout=out)
        p.refresh_from_db()
        self.assertEqual(p.content_type, "not_movie")
        self.assertGreater(p.classification_confidence, 0)

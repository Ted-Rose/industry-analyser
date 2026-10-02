import datetime
import json
import pathlib
from types import SimpleNamespace
from unittest import skipIf

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from scrape_jobs.models import ScrapeJobRunItem
from scrape_jobs.runner import ScrapeJobRunner
from tv_programs.classification import EXCLUDED_LOCAL_SHOWS, classify
from tv_programs.dedup import (
    annotate_result,
    compute_dedup_key,
    get_or_create_show,
    normalize_title,
    parse_series_info,
)
from tv_programs.enrichment import OMDbClient, enrich_show
from tv_programs.models import Channel, Program, Show, ShowPreference
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

    def test_parse_captures_source_event_id_and_dedup(self):
        resp = SimpleNamespace(data=self.data)
        out = self.scraper.parse_results(resp)
        self.assertEqual(
            [p["source_event_id"] for p in out],
            ["1111111111111", "2222222222222", "3333333333333"],
        )
        for p in out:
            self.assertEqual(len(p["dedup_key"]), 64)
            self.assertEqual(p["title_norm"], normalize_title(p["title_lv"]))


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


class DedupTests(TestCase):
    """normalize_title / parse_series_info / dedup key behaviour."""

    def test_normalize_title_strips_rerun_marker(self):
        self.assertEqual(
            normalize_title("Kultūršoks (atkārtojums)"), "Kultūršoks"
        )
        self.assertEqual(
            normalize_title("Garainis. 3. sezona (Atkārtojums)"),
            "Garainis. 3. sezona",
        )
        self.assertEqual(normalize_title("  Panorāma.  "), "Panorāma")

    def test_series_info_telenovela(self):
        info = parse_series_info(
            "Mīlas viesulis 21. Vācijas seriāls. 4471. sērija"
        )
        self.assertEqual(info["series_title"], "Mīlas viesulis")
        self.assertEqual(info["season"], 21)
        self.assertEqual(info["episode"], 4471)

    def test_series_info_inline_season(self):
        info = parse_series_info(
            "Solījums 4. Spānijas telenovele. 613. sērija"
        )
        self.assertEqual(info["series_title"], "Solījums")
        self.assertEqual(info["season"], 4)
        self.assertEqual(info["episode"], 613)

    def test_series_info_nosl_episode(self):
        info = parse_series_info(
            "Alpu dakteris 13. Seriāls. 14. (nosl.) sērija"
        )
        self.assertEqual(info["series_title"], "Alpu dakteris")
        self.assertEqual(info["season"], 13)
        self.assertEqual(info["episode"], 14)

    def test_series_info_episode_only(self):
        info = parse_series_info(
            "Māja pie ezera. Daudzsēriju filma. 10. sērija"
        )
        self.assertEqual(info["series_title"], "Māja pie ezera")
        self.assertIsNone(info["season"])
        self.assertEqual(info["episode"], 10)

    def test_series_info_sezona_word(self):
        info = parse_series_info("Garainis. 3. sezona")
        self.assertEqual(info["series_title"], "Garainis")
        self.assertEqual(info["season"], 3)
        self.assertIsNone(info["episode"])

    def test_series_info_movie(self):
        info = parse_series_info("Sirds robeža")
        self.assertEqual(info["series_title"], "")
        self.assertIsNone(info["season"])
        self.assertIsNone(info["episode"])

    def test_dedup_key_ignores_rerun_marker(self):
        a = annotate_result({"title_lv": "Sirds robeža",
                             "description_lv": "Desc."})
        b = annotate_result({"title_lv": "Sirds robeža (atkārtojums)",
                             "description_lv": "Desc."})
        self.assertEqual(a["dedup_key"], b["dedup_key"])

    def test_dedup_key_differs_by_episode(self):
        a = compute_dedup_key(
            "Solījums 4. Spānijas telenovele. 612. sērija", "d", 4, 612
        )
        b = compute_dedup_key(
            "Solījums 4. Spānijas telenovele. 613. sērija", "d", 4, 613
        )
        self.assertNotEqual(a, b)


class ShowDedupTests(TestCase):
    """Scraper <-> Show wiring: reruns share one Show, excluded titles
    (incl. '(atkārtojums)' variants) are dropped."""

    def setUp(self):
        self.channel = Channel.objects.create(name="ltv1_hd")
        self.scraper = TVProgramScraper(enrich=False)
        self.scraper.current_channel = self.channel
        self.scraper.current_start_time = timezone.make_aware(
            datetime.datetime(2026, 10, 1, 0, 0, 0),
            datetime.timezone.utc,
        )

    def _parsed(self, title, hour=20, event_id="e1", desc="Apraksts."):
        return annotate_result({
            "title_lv": title,
            "description_lv": desc,
            "start_time": self.scraper.current_start_time.replace(
                hour=hour
            ),
            "duration_minutes": 60,
            "image_url": "",
            "channel": self.channel,
            "classification": classify(title, desc, "ltv1_hd", 60),
            "source_event_id": event_id,
        })

    def test_rerun_of_same_episode_dedups_to_one_show(self):
        p1 = self._parsed("Solījums 4. Telenovele. 612. sērija",
                          hour=10, event_id="a")
        p2 = self._parsed(
            "Solījums 4. Telenovele. 612. sērija (atkārtojums)",
            hour=18, event_id="b",
        )
        r1 = self.scraper.enrich_result(p1)
        r2 = self.scraper.enrich_result(p2)
        self.assertEqual(r1["show"].pk, r2["show"].pk)
        self.assertEqual(Show.objects.count(), 1)

    def test_exclusion_catches_atkārtojums_variant(self):
        programs = [
            self._parsed("Kultūršoks (atkārtojums)"),
            self._parsed("Sirds robeža"),
        ]
        kept = self.scraper.remove_redundant_results(programs)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["title_lv"], "Sirds robeža")

    def test_known_show_airing_is_kept_with_show_attached(self):
        show = Show.objects.create(
            title_lv="Sirds robeža",
            dedup_key=compute_dedup_key(
                "Sirds robeža", "Apraksts.", None, None
            ),
        )
        programs = [self._parsed("Sirds robeža", event_id="c")]
        kept = self.scraper.remove_redundant_results(programs)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["show"].pk, show.pk)

    def test_existing_airing_is_dropped(self):
        parsed = self._parsed("Sirds robeža", event_id="d")
        show = Show.objects.create(
            title_lv="Sirds robeža", dedup_key=parsed["dedup_key"]
        )
        Program.objects.create(
            show=show,
            channel=self.channel,
            start_time=parsed["start_time"],
            title_lv="Sirds robeža",
        )
        kept = self.scraper.remove_redundant_results([parsed])
        self.assertEqual(kept, [])

    def test_duplicate_event_id_is_dropped(self):
        parsed = self._parsed("Sirds robeža", event_id="dup-event")
        Program.objects.create(
            source_event_id="dup-event",
            channel=self.channel,
            start_time=parsed["start_time"],
            title_lv="Sirds robeža",
        )
        kept = self.scraper.remove_redundant_results([parsed])
        self.assertEqual(kept, [])


class OMDbClientTests(TestCase):
    @staticmethod
    def _resp(payload):
        return SimpleNamespace(
            status=200, data=json.dumps(payload).encode()
        )

    def test_exact_hit(self):
        calls = []

        def rf(url):
            calls.append(url)
            return self._resp({
                "Response": "True",
                "Title": "The Matrix",
                "imdbID": "tt0133093",
            })

        client = OMDbClient(rf, "key", min_interval=0)
        data = client.search_title("The Matrix")
        self.assertEqual(data["imdbID"], "tt0133093")
        self.assertEqual(len(calls), 1)
        self.assertIn("apikey=key", calls[0])

    def test_search_fallback_picks_best_and_fetches(self):
        calls = []

        def rf(url):
            calls.append(url)
            if "s=" in url:
                return self._resp({
                    "Response": "True",
                    "Search": [
                        {"Title": "Unrelated", "imdbID": "tt0000001"},
                        {"Title": "The Matrix", "imdbID": "tt0133093"},
                    ],
                })
            if "i=" in url:
                return self._resp({
                    "Response": "True",
                    "Title": "The Matrix",
                    "imdbID": "tt0133093",
                })
            return self._resp({"Response": "False"})

        client = OMDbClient(rf, "key", min_interval=0)
        data = client.search_title("Matrix")
        self.assertEqual(data["imdbID"], "tt0133093")
        self.assertTrue(any("i=tt0133093" in c for c in calls))


class EnrichShowTests(TestCase):
    @staticmethod
    def _resp(payload):
        return SimpleNamespace(
            status=200, data=json.dumps(payload).encode()
        )

    def test_omdb_fields_applied(self):
        show = Show.objects.create(
            title_lv="Matrikss", dedup_key="k1"
        )

        def rf(url):
            return self._resp({
                "Response": "True",
                "Title": "The Matrix",
                "Plot": "A hacker learns the truth.",
                "imdbRating": "8.7",
                "Rated": "R",
                "Year": "1999",
                "Poster": "https://img/p.jpg",
                "imdbID": "tt0133093",
            })

        omdb = OMDbClient(rf, "key", min_interval=0)
        enrich_show(show, omdb=omdb)
        show.refresh_from_db()
        self.assertEqual(show.enrichment_status, "enriched")
        self.assertEqual(show.enrichment_source, "omdb")
        self.assertEqual(show.imdb_id, "tt0133093")
        self.assertEqual(
            show.imdb_url, "https://www.imdb.com/title/tt0133093/"
        )
        self.assertEqual(str(show.imdb_rating), "8.7")
        self.assertEqual(show.pg_rating, "R")
        self.assertEqual(show.year, "1999")
        self.assertEqual(show.image_url, "https://img/p.jpg")

    def test_cinemeta_fallback_when_omdb_misses(self):
        show = Show.objects.create(
            title_lv="The Matrix", dedup_key="k2"
        )

        def rf(url):
            if "search=" in url:
                return self._resp({
                    "metas": [{"id": "tt0133093", "name": "The Matrix"}]
                })
            return self._resp({
                "meta": {
                    "imdb_id": "tt0133093",
                    "name": "The Matrix",
                    "imdbRating": "8.7",
                    "releaseInfo": "1999",
                }
            })

        def always_miss(url):
            return self._resp({"Response": "False"})

        omdb = OMDbClient(always_miss, "key", min_interval=0)
        enrich_show(show, omdb=omdb, request_fn=rf)
        show.refresh_from_db()
        self.assertEqual(show.enrichment_status, "enriched")
        self.assertEqual(show.enrichment_source, "cinemeta")
        self.assertEqual(show.imdb_id, "tt0133093")
        self.assertEqual(str(show.imdb_rating), "8.7")

    def test_cinemeta_rejects_dissimilar_hit(self):
        """Junk search hits ('Slow TV: Migla' -> 'SM:TV Live') must not
        produce wrong IMDb links."""
        show = Show.objects.create(
            title_lv="Slow TV: Migla", dedup_key="k2b"
        )

        def rf(url):
            if "search=" in url:
                return self._resp({
                    "metas": [{"id": "tt0267217", "name": "SM:TV Live"}]
                })
            return self._resp({"meta": {"imdb_id": "tt0267217"}})

        omdb = OMDbClient(
            lambda url: self._resp({"Response": "False"}),
            "key", min_interval=0,
        )
        enrich_show(show, omdb=omdb, request_fn=rf)
        show.refresh_from_db()
        self.assertEqual(show.enrichment_status, "not_found")
        self.assertIsNone(show.imdb_id)

    def test_not_found_status(self):
        show = Show.objects.create(title_lv="Neatrodams", dedup_key="k3")

        def rf(url):
            return self._resp({"Response": "False"})

        def cinemeta_miss(url):
            return self._resp({"metas": []})

        omdb = OMDbClient(rf, "key", min_interval=0)
        enrich_show(show, omdb=omdb, request_fn=cinemeta_miss)
        show.refresh_from_db()
        self.assertEqual(show.enrichment_status, "not_found")

    def test_failed_status_on_exception(self):
        show = Show.objects.create(title_lv="Bojāts", dedup_key="k4")

        class Boom:
            def search_title(self, *a, **k):
                raise RuntimeError("boom")

        enrich_show(show, omdb=Boom())
        show.refresh_from_db()
        self.assertEqual(show.enrichment_status, "failed")


class ReactViewTests(TestCase):
    def setUp(self):
        self.show = Show.objects.create(
            title_lv="Sirds robeža", dedup_key="r1"
        )

    def _url(self, reaction):
        return reverse(
            "tv_programs:react_to_show",
            args=[self.show.pk, reaction],
        )

    def test_like_toggle(self):
        self.client.post(self._url("like"))
        pref = ShowPreference.objects.get(show=self.show)
        self.assertEqual(pref.reaction, "like")
        self.assertIsNone(pref.user)
        self.client.post(self._url("like"))
        self.assertFalse(
            ShowPreference.objects.filter(show=self.show).exists()
        )

    def test_like_then_dislike_switches(self):
        self.client.post(self._url("like"))
        self.client.post(self._url("dislike"))
        pref = ShowPreference.objects.get(show=self.show)
        self.assertEqual(pref.reaction, "dislike")

    def test_invalid_reaction_rejected(self):
        resp = self.client.post(self._url("meh"))
        self.assertEqual(resp.status_code, 400)

    def test_react_requires_post(self):
        resp = self.client.get(self._url("like"))
        self.assertEqual(resp.status_code, 405)


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

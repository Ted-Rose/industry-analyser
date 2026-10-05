import datetime
import json
import pathlib
from types import SimpleNamespace
from unittest import mock, skipIf

from django.contrib.auth import get_user_model
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


def make_channel(name="ltv1_hd"):
    return Channel.objects.create(name=name)


def make_show(dedup_key="s1", **kwargs):
    return Show.objects.create(
        title_lv=kwargs.pop("title_lv", "Sirds robeža"),
        dedup_key=dedup_key,
        **kwargs,
    )


def make_program(channel=None, start_time=None, **kwargs):
    if channel is None:
        channel, _ = Channel.objects.get_or_create(name="ltv1_hd")
    return Program.objects.create(
        title_lv=kwargs.pop("title_lv", "Dienas ziņas"),
        description_lv=kwargs.pop("description_lv", ""),
        channel=channel,
        start_time=start_time or timezone.now(),
        duration_minutes=kwargs.pop("duration_minutes", 25),
        **kwargs,
    )


class TvApiTests(TestCase):
    """HTTP-layer coverage for the tv SPA API (mounted at
    /api/tv/) and the URL cutover — the retired program_list /
    react_to_show views' behavior is covered here at the JSON
    boundary."""

    API = "/api/tv"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="alice", password="pw"
        )

    # --- URL cutover / shell ---

    def test_tv_url_serves_shell(self):
        resp = self.client.get("/tv/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="root"')
        self.assertContains(resp, "spa-bootstrap")

    def test_tv_deep_link_serves_shell(self):
        resp = self.client.get("/tv/spoki-page/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="root"')

    def test_non_get_to_spa_urls_404s(self):
        for method in ("post", "put", "delete"):
            resp = getattr(self.client, method)("/tv/")
            self.assertEqual(resp.status_code, 404)

    def test_retired_react_url_post_404s(self):
        """POSTs to the old react/<uuid>/<reaction>/ form action hit
        the catch-all shell, which only answers GET/HEAD — retired
        mutation URLs must not answer with HTML."""
        show = make_show()
        resp = self.client.post(f"/tv/react/{show.pk}/like/")
        self.assertEqual(resp.status_code, 404)
        # ...but a GET deep link still serves the SPA shell.
        resp = self.client.get(f"/tv/react/{show.pk}/like/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="root"')

    def test_named_routes_still_reverse(self):
        self.assertEqual(
            reverse("tv_programs:program_list"), "/tv/"
        )
        self.assertEqual(
            reverse("tv_programs:spoki_page"), "/tv/spoki-page/"
        )

    # --- GET /api/tv/programs/ ---

    def test_program_list_is_public(self):
        make_program()
        resp = self.client.get(f"{self.API}/programs/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["programs"]), 1)
        self.assertIn("channels", body)
        self.assertIn("filters", body)

    def test_default_window_excludes_old_programs(self):
        old = make_program(
            start_time=timezone.now() - datetime.timedelta(days=30)
        )
        recent = make_program()
        resp = self.client.get(f"{self.API}/programs/")
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertIn(str(recent.pk), ids)
        self.assertNotIn(str(old.pk), ids)

    def test_explicit_date_window(self):
        ch = make_channel()
        make_program(
            channel=ch,
            start_time=datetime.datetime(
                2026, 1, 5, 12, 0, tzinfo=datetime.timezone.utc
            ),
        )
        outside = make_program(
            channel=ch,
            start_time=datetime.datetime(
                2026, 1, 20, 12, 0, tzinfo=datetime.timezone.utc
            ),
        )
        resp = self.client.get(
            f"{self.API}/programs/",
            {"start_date": "2026-01-01", "end_date": "2026-01-10"},
        )
        body = resp.json()
        self.assertEqual(len(body["programs"]), 1)
        self.assertNotIn(
            str(outside.pk),
            [p["id"] for p in body["programs"]],
        )
        # Effective window is echoed back like the template's
        # filters context.
        self.assertEqual(body["filters"]["start_date"], "2026-01-01")
        self.assertEqual(body["filters"]["end_date"], "2026-01-10")

    def test_default_excludes_r_rated_shows(self):
        """not_content_rating defaults to 'R' — a program linked to
        an R-rated show is hidden; shows without a rating and
        unlinked programs stay."""
        r_show = make_show("r", pg_rating="R")
        pg_show = make_show("pg", pg_rating="PG-13")
        ch = make_channel()
        hidden = make_program(channel=ch, show=r_show)
        shown = make_program(channel=ch, show=pg_show)
        unlinked = make_program(channel=ch)
        resp = self.client.get(f"{self.API}/programs/")
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertNotIn(str(hidden.pk), ids)
        self.assertIn(str(shown.pk), ids)
        self.assertIn(str(unlinked.pk), ids)

    def test_empty_not_content_rating_disables_exclusion(self):
        r_show = make_show("r", pg_rating="R")
        prog = make_program(show=r_show)
        resp = self.client.get(
            f"{self.API}/programs/", {"not_content_rating": ""}
        )
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertIn(str(prog.pk), ids)
        self.assertEqual(
            resp.json()["filters"]["not_content_rating"], ""
        )

    def test_content_rating_filter(self):
        pg_show = make_show("pg", pg_rating="PG-13")
        r_show = make_show("r", pg_rating="R")
        ch = make_channel()
        kept = make_program(channel=ch, show=pg_show)
        make_program(channel=ch, show=r_show)
        resp = self.client.get(
            f"{self.API}/programs/",
            {"content_rating": "PG-13"},
        )
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertEqual(ids, [str(kept.pk)])

    def test_rating_value_filters_on_show_rating(self):
        high = make_show("h", imdb_rating=8.5)
        low = make_show("l", imdb_rating=5.0)
        ch = make_channel()
        kept = make_program(channel=ch, show=high)
        make_program(channel=ch, show=low)
        resp = self.client.get(
            f"{self.API}/programs/", {"rating_value": "7.0"}
        )
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertEqual(ids, [str(kept.pk)])

    def test_channel_and_exclude_channel_filters(self):
        ltv = make_channel("ltv1_hd")
        other = make_channel("tv3")
        kept = make_program(channel=ltv)
        make_program(channel=other)
        resp = self.client.get(
            f"{self.API}/programs/", {"channel": "ltv1_hd"}
        )
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertEqual(ids, [str(kept.pk)])
        resp = self.client.get(
            f"{self.API}/programs/", {"exclude_channel": "tv3"}
        )
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertEqual(ids, [str(kept.pk)])

    def test_anonymous_dislike_hides_program(self):
        """An anonymous (user-NULL) dislike hides the show — and any
        sibling sharing its series_title — for every visitor."""
        show = make_show("a", series_title="Seriāls")
        sibling = make_show("b", series_title="Seriāls")
        ch = make_channel()
        hidden = make_program(channel=ch, show=show)
        hidden_sibling = make_program(channel=ch, show=sibling)
        visible = make_program(channel=ch)
        ShowPreference.objects.create(
            show=show, reaction="dislike", user=None
        )
        resp = self.client.get(f"{self.API}/programs/")
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertNotIn(str(hidden.pk), ids)
        self.assertNotIn(str(hidden_sibling.pk), ids)
        self.assertIn(str(visible.pk), ids)

    def test_non_movie_dislike_hides_same_title_shows(self):
        """Daily slots carry no series markers — each airing is a
        distinct Show (the dedup key covers description) with an
        empty series_title, so the non-movie dislike falls back to
        hiding every Show sharing its title_lv."""
        show = make_show(
            "a", title_lv="Bez Tabu", content_type="not_movie"
        )
        next_ep = make_show(
            "b", title_lv="Bez Tabu", content_type="not_movie",
            description_lv="next day's episode",
        )
        ch = make_channel()
        hidden = make_program(channel=ch, show=show)
        hidden_next = make_program(channel=ch, show=next_ep)
        visible = make_program(
            channel=ch, show=make_show("c", title_lv="Cits raidījums")
        )
        ShowPreference.objects.create(
            show=show, reaction="dislike", user=None
        )
        resp = self.client.get(f"{self.API}/programs/")
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertNotIn(str(hidden.pk), ids)
        self.assertNotIn(str(hidden_next.pk), ids)
        self.assertIn(str(visible.pk), ids)

    def test_movie_dislike_hides_only_that_show(self):
        """Movies never series-hide — a sibling sharing series_title
        stays in the feed."""
        show = make_show(
            "a", series_title="Māja pie ezera",
            content_type="movie",
        )
        sibling = make_show(
            "b", series_title="Māja pie ezera",
            content_type="movie",
        )
        ch = make_channel()
        hidden = make_program(channel=ch, show=show)
        kept = make_program(channel=ch, show=sibling)
        ShowPreference.objects.create(
            show=show, reaction="dislike", user=None
        )
        resp = self.client.get(f"{self.API}/programs/")
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertNotIn(str(hidden.pk), ids)
        self.assertIn(str(kept.pk), ids)

    def test_show_disliked_reveals_with_reaction_flag(self):
        show = make_show("a")
        prog = make_program(show=show)
        ShowPreference.objects.create(
            show=show, reaction="dislike", user=None
        )
        resp = self.client.get(
            f"{self.API}/programs/", {"show_disliked": "1"}
        )
        body = resp.json()
        ids = [p["id"] for p in body["programs"]]
        self.assertIn(str(prog.pk), ids)
        row = next(
            p for p in body["programs"] if p["id"] == str(prog.pk)
        )
        self.assertEqual(row["user_reaction"], "dislike")
        self.assertTrue(body["filters"]["show_disliked"])

    def test_other_users_preference_invisible_to_anonymous(self):
        """An authenticated user's dislike must not hide the show
        for anonymous visitors."""
        show = make_show("a")
        prog = make_program(show=show)
        ShowPreference.objects.create(
            show=show, reaction="dislike", user=self.user
        )
        resp = self.client.get(f"{self.API}/programs/")
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertIn(str(prog.pk), ids)

    def test_authenticated_sees_own_and_anonymous_prefs(self):
        """The logged-in view merges the anonymous bucket with the
        user's own rows — an anon dislike still hides for them."""
        show = make_show("a")
        prog = make_program(show=show)
        ShowPreference.objects.create(
            show=show, reaction="dislike", user=None
        )
        self.client.force_login(self.user)
        resp = self.client.get(f"{self.API}/programs/")
        ids = [p["id"] for p in resp.json()["programs"]]
        self.assertNotIn(str(prog.pk), ids)
        # ...and with show_disliked=1 they see their merged reaction.
        resp = self.client.get(
            f"{self.API}/programs/", {"show_disliked": "1"}
        )
        row = resp.json()["programs"][0]
        self.assertEqual(row["user_reaction"], "dislike")

    def test_channels_option_list(self):
        make_channel("ltv1_hd")
        make_channel("tv3")
        resp = self.client.get(f"{self.API}/programs/")
        self.assertEqual(
            resp.json()["channels"], ["ltv1_hd", "tv3"]
        )

    def test_invalid_date_param_422s(self):
        resp = self.client.get(
            f"{self.API}/programs/", {"start_date": "last week"}
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"], "validation_error")

    # --- GET /api/tv/spoki-page/ ---

    def test_spoki_page_returns_title_and_content(self):
        html = (
            '<html><head><title>Spoki TV</title></head><body>'
            '<div class="show-memoir__text editor-text-content">'
            '<p>Šodien TV</p></div></body></html>'
        )
        fake = mock.Mock(text=html)
        fake.raise_for_status = lambda: None
        with mock.patch(
            'tv_programs.views.requests.get', return_value=fake
        ) as get:
            resp = self.client.get(f'{self.API}/spoki-page/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['title'], 'Spoki TV')
        self.assertIn('Šodien TV', body['content'])
        get.assert_called_once()

    def test_spoki_page_fetch_failure_returns_message(self):
        import requests as _requests
        with mock.patch(
            'tv_programs.views.requests.get',
            side_effect=_requests.ConnectionError('down'),
        ):
            resp = self.client.get(f'{self.API}/spoki-page/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Failed', resp.json()['content'])

    # --- POST /api/tv/shows/{pk}/react/{reaction}/ ---

    def _react_url(self, show, reaction):
        return f"{self.API}/shows/{show.pk}/react/{reaction}/"

    def test_react_unauthenticated_401(self):
        """The old form allowed anonymous likes; the API endpoint
        keeps session auth — anonymous POSTs get a JSON 401 whose
        login_url points back at the SPA, not the API URL."""
        show = make_show()
        resp = self.client.post(self._react_url(show, "like"))
        self.assertEqual(resp.status_code, 401)
        body = resp.json()
        self.assertEqual(body["error"], "unauthenticated")
        self.assertIn("next=%2Ftv%2F", body["login_url"])

    def test_react_like_toggle(self):
        self.client.force_login(self.user)
        show = make_show()
        resp = self.client.post(self._react_url(show, "like"))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["reaction"], "like")
        pref = ShowPreference.objects.get(show=show)
        self.assertEqual(pref.reaction, "like")
        self.assertEqual(pref.user, self.user)
        # Same reaction again removes it (the old toggle).
        resp = self.client.post(self._react_url(show, "like"))
        self.assertTrue(resp.json()["success"])
        self.assertIsNone(resp.json()["reaction"])
        self.assertFalse(
            ShowPreference.objects.filter(show=show).exists()
        )

    def test_react_like_then_dislike_switches(self):
        self.client.force_login(self.user)
        show = make_show()
        self.client.post(self._react_url(show, "like"))
        self.client.post(self._react_url(show, "dislike"))
        pref = ShowPreference.objects.get(show=show)
        self.assertEqual(pref.reaction, "dislike")

    def test_react_invalid_reaction_400(self):
        self.client.force_login(self.user)
        show = make_show()
        resp = self.client.post(self._react_url(show, "meh"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "unknown_reaction")

    def test_react_unknown_show_404s(self):
        import uuid

        self.client.force_login(self.user)
        resp = self.client.post(
            f"{self.API}/shows/{uuid.uuid4()}/react/like/"
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"], "not_found")

    def test_react_csrf_enforced(self):
        csrf_client = self.client.__class__(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        show = make_show()
        resp = csrf_client.post(self._react_url(show, "like"))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"], "forbidden")

    # --- POST /api/tv/programs/{pk}/react/{reaction}/ ---

    def _program_react_url(self, program, reaction):
        return f"{self.API}/programs/{program.pk}/react/{reaction}/"

    def test_react_to_program_unauthenticated_401(self):
        resp = self.client.post(
            self._program_react_url(make_program(), "like")
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"], "unauthenticated")

    def test_react_to_program_links_unlinked_program(self):
        """An airing without a Show lazily resolves its canonical
        one — created from the program's fields via the same dedup
        path as backfill_program_shows — and links it."""
        self.client.force_login(self.user)
        prog = make_program(title_lv="Bez Tabu")
        self.assertIsNone(prog.show)
        resp = self.client.post(self._program_react_url(prog, "dislike"))
        self.assertEqual(resp.status_code, 200)
        prog.refresh_from_db()
        show = prog.show
        self.assertIsNotNone(show)
        self.assertEqual(show.title_lv, "Bez Tabu")
        self.assertEqual(str(show.pk), resp.json()["show_id"])
        pref = ShowPreference.objects.get(user=self.user)
        self.assertEqual(pref.show, show)
        self.assertEqual(pref.reaction, "dislike")
        # The same dedup key is reused — reacting on a second
        # identical airing doesn't create another Show.
        twin = make_program(title_lv="Bez Tabu")
        self.client.post(self._program_react_url(twin, "like"))
        twin.refresh_from_db()
        self.assertEqual(twin.show, show)
        self.assertEqual(
            ShowPreference.objects.get(user=self.user).reaction,
            "like",
        )

    def test_react_to_program_uses_linked_show(self):
        self.client.force_login(self.user)
        show = make_show()
        prog = make_program(show=show)
        resp = self.client.post(self._program_react_url(prog, "like"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["show_id"], str(show.pk))
        pref = ShowPreference.objects.get(user=self.user)
        self.assertEqual(pref.show, show)

    def test_react_to_program_collision_still_reacts(self):
        """A program colliding on (show, channel, start_time) can't
        be linked, but the preference still lands on the resolved
        Show."""
        self.client.force_login(self.user)
        show = make_show(
            "s", title_lv="Bez Tabu", description_lv=None
        )
        from tv_programs.dedup import annotate_result

        info = annotate_result({
            "title_lv": "Bez Tabu",
            "description_lv": "",
        })
        Show.objects.filter(pk=show.pk).update(
            dedup_key=info["dedup_key"]
        )
        show.refresh_from_db()
        occupied = make_program(
            title_lv="Bez Tabu", description_lv="", show=show
        )
        blocker = make_program(
            title_lv="Bez Tabu", description_lv="",
            channel=occupied.channel, start_time=occupied.start_time,
        )
        self.assertIsNone(blocker.show)
        resp = self.client.post(
            self._program_react_url(blocker, "dislike")
        )
        self.assertEqual(resp.status_code, 200)
        blocker.refresh_from_db()
        self.assertIsNone(blocker.show)
        self.assertEqual(
            ShowPreference.objects.get(user=self.user).show, show
        )

    def test_react_to_program_invalid_reaction_400(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            self._program_react_url(make_program(), "meh")
        )
        self.assertEqual(resp.status_code, 400)

    def test_react_to_program_unknown_404s(self):
        import uuid

        self.client.force_login(self.user)
        resp = self.client.post(
            f"{self.API}/programs/{uuid.uuid4()}/react/like/"
        )
        self.assertEqual(resp.status_code, 404)


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

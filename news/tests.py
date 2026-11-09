"""Tests for the news app — RSS parsing, idempotent upsert,
keyword topic classification, story clustering, digest build."""
import contextlib
import hashlib
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone as dtz
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from google.oauth2 import service_account
from langdetect import LangDetectException
from langdetect.lang_detect_exception import ErrorCode

from scrape_jobs.models import (
    ScrapeJob,
    ScrapeJobItem,
    ScrapeJobRun,
    ScrapeJobRunItem,
)
from scrape_jobs.runner import (
    ScrapeJobRunner,
    cycle_scrape_exists,
    ensure_job,
)

from .audio import AudioGenerationError, text_to_audio
from .backfill import (
    BACKFILL_STRATEGIES,
    ArchiveMonthStrategy,
    ChunkProbeSitemapStrategy,
    MonthSitemapStrategy,
    NewsBackfillScraper,
    Partition,
    WeekSitemapStrategy,
    extract_article_metadata,
    normalize_link,
    parse_sitemap_xml,
)
from .classification import classify_topic
from .clustering import _refresh_story, link_unmatched_articles
from .digest import build_digest
from .models import (
    NewsArticle,
    NewsArticleAudio,
    NewsDigest,
    NewsDigestItem,
    NewsDigestTask,
    NewsSource,
    NewsSourcePreference,
    NewsStory,
    NewsTopic,
)
from .preferences import ordered_sources, ordered_story_articles
from .scraper import NewsScraper
from .topics import TOPICS

FEED_A = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Feed A</title>
<item>
  <title>Saeima pie&#x113;&#x107;em 2027. gada bud&#x17E;etu</title>
  <link>https://a.lv/raksts/zinas/latvija/saeima-budzets</link>
  <pubDate>Wed, 29 Oct 2026 10:00:00 +0200</pubDate>
  <guid>feed-a-1</guid>
  <description>&lt;p&gt;Vald&#x12B;bas
  bud&#x17E;ets apstiprin&#x101;ts.&lt;/p&gt;</description>
  <enclosure url="https://a.lv/img1.jpg" type="image/jpeg"/>
  <category>Zi&#x146;as</category>
  <category>Latvija</category>
</item>
<item>
  <title>Zi&#x146;a bez guid</title>
  <link>https://a.lv/raksts/zinas/latvija/bez-guid</link>
  <pubDate>Wed, 29 Oct 2026 11:00:00 +0200</pubDate>
  <description>plain text lead</description>
</item>
<item>
  <title>Tre&#x161;&#x101; zi&#x146;a</title>
  <link>https://a.lv/raksts/sports/tresa</link>
  <guid>feed-a-3</guid>
</item>
</channel>
</rss>"""

FEED_B = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Feed B</title>
<item>
  <title>Pirmais B</title>
  <link>https://b.lv/x/1</link>
  <guid>b-1</guid>
</item>
<item>
  <title>Otrais B</title>
  <link>https://b.lv/x/2</link>
  <guid>b-2</guid>
</item>
<item>
  <title>Tre&#x161;ais B</title>
  <link>https://b.lv/x/3</link>
  <guid>b-3</guid>
</item>
</channel>
</rss>"""


def _response(data, status=200, headers=None):
    return SimpleNamespace(
        data=data, status=status, headers=headers or {}
    )


def _source(slug='a', strategy='tag', **kw):
    return NewsSource.objects.create(
        slug=slug,
        name=slug.upper(),
        feed_url=f'https://{slug}.lv/rss',
        category_strategy=strategy,
        **kw,
    )


class ParseResultsTests(TestCase):
    def setUp(self):
        self.source = _source('a', 'tag')
        self.scraper = NewsScraper()
        self.scraper._active_source = self.source

    def test_extracts_all_fields(self):
        results = self.scraper.parse_results(_response(FEED_A))
        self.assertEqual(len(results), 3)
        first = results[0]
        self.assertEqual(first['external_id'], 'feed-a-1')
        self.assertEqual(
            first['link'],
            'https://a.lv/raksts/zinas/latvija/saeima-budzets',
        )
        self.assertIn('Saeima', first['title'])
        # HTML-entity description is stripped to plain text.
        self.assertNotIn('<p>', first['lead'])
        self.assertIn('apstiprin', first['lead'])
        self.assertEqual(first['image_url'], 'https://a.lv/img1.jpg')
        self.assertEqual(first['feed_categories'], ['Ziņas', 'Latvija'])
        self.assertEqual(first['published_at'].year, 2026)
        self.assertEqual(first['published_at'].month, 10)
        self.assertIsNotNone(first['published_at'].tzinfo)

    def test_guid_missing_falls_back_to_link_hash(self):
        results = self.scraper.parse_results(_response(FEED_A))
        second = results[1]
        expected = hashlib.sha256(
            second['link'].encode()
        ).hexdigest()[:32]
        self.assertEqual(second['external_id'], expected)

    def test_url_strategy_categories_from_link_path(self):
        self.source.category_strategy = 'url'
        results = self.scraper.parse_results(_response(FEED_A))
        self.assertEqual(
            results[0]['feed_categories'], ['zinas', 'latvija']
        )

    def test_none_and_bad_response(self):
        self.assertEqual(self.scraper.parse_results(None), [])
        self.assertEqual(
            self.scraper.parse_results(_response(b'not xml <')), []
        )

    def test_opaque_guid_without_link_is_skipped(self):
        feed = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Bez saites</title>
<guid isPermaLink="false">opaque-123</guid></item>
<item><title>Ar saiti</title><link>https://a.lv/ok</link>
<guid>g-2</guid></item>
</channel></rss>"""
        results = self.scraper.parse_results(_response(feed))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['external_id'], 'g-2')

    def test_dc_date_iso_fallback_and_naive_tz(self):
        feed = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
<item><title>ISO</title><link>https://a.lv/iso</link>
<guid>iso-1</guid>
<dc:date>2026-10-29T10:00:00+02:00</dc:date></item>
<item><title>Naive</title><link>https://a.lv/naive</link>
<guid>iso-2</guid>
<dc:date>2026-10-29T10:00:00</dc:date></item>
</channel></rss>"""
        results = self.scraper.parse_results(_response(feed))
        self.assertEqual(
            results[0]['published_at'].isoformat(),
            '2026-10-29T10:00:00+02:00',
        )
        # A naive ISO value is localized, not dropped or warned.
        self.assertIsNotNone(results[1]['published_at'].tzinfo)


class CreateOrUpdateTests(TestCase):
    def setUp(self):
        self.source = _source('a', 'tag')
        self.scraper = NewsScraper()
        self.scraper._active_source = self.source

    def _scrape(self):
        results = self.scraper.parse_results(_response(FEED_A))
        results = self.scraper.remove_redundant_results(results)
        articles = self.scraper.initiate_resources(results)
        self.scraper.create_or_update_resources(articles)

    def test_second_run_is_idempotent(self):
        self._scrape()
        self.assertEqual(NewsArticle.objects.count(), 3)
        old_seen = timezone.now() - timedelta(days=1)
        NewsArticle.objects.update(last_seen=old_seen)
        self._scrape()
        self.assertEqual(NewsArticle.objects.count(), 3)
        for article in NewsArticle.objects.all():
            self.assertGreater(article.last_seen, old_seen)

    def test_in_session_dedup(self):
        dup = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>T1</title><link>https://a.lv/1</link>
<guid>same</guid></item>
<item><title>T2</title><link>https://a.lv/2</link>
<guid>same</guid></item>
</channel></rss>"""
        results = self.scraper.parse_results(_response(dup))
        deduped = self.scraper.remove_redundant_results(results)
        self.assertEqual(len(deduped), 1)


class StatefulScrapeTests(TestCase):
    """Conditional GET per feed plus the known-item skip: a
    304 touches nothing, a 200 stores fresh validators on the
    source, and a repeat pass only bumps last_seen."""

    def setUp(self):
        self.source = _source('a', 'tag')
        self.scraper = NewsScraper()
        self.scraper._active_source = self.source

    def test_304_touches_nothing(self):
        self.source.etag = '"v1"'
        self.source.last_modified = 'Wed, 29 Oct 2026 10:00:00 GMT'
        self.source.save()
        response = _response(b'', status=304)
        with patch.object(
            NewsScraper, 'make_request', return_value=response
        ):
            result = self.scraper.scrape_portal(
                self.source.feed_url
            )
        self.assertIsNone(result)
        self.assertEqual(NewsArticle.objects.count(), 0)
        self.source.refresh_from_db()
        self.assertEqual(self.source.etag, '"v1"')
        self.assertEqual(
            self.source.last_modified,
            'Wed, 29 Oct 2026 10:00:00 GMT',
        )

    def test_200_stores_feed_validators(self):
        response = _response(
            FEED_A,
            headers={
                'ETag': '"v2"',
                'Last-Modified': 'Thu, 30 Oct 2026 08:00:00 GMT',
            },
        )
        with patch.object(
            NewsScraper, 'make_request', return_value=response
        ):
            articles = self.scraper.scrape_portal(
                self.source.feed_url
            )
        self.scraper.create_or_update_resources(articles)
        self.source.refresh_from_db()
        self.assertEqual(self.source.etag, '"v2"')
        self.assertEqual(
            self.source.last_modified,
            'Thu, 30 Oct 2026 08:00:00 GMT',
        )
        self.assertEqual(NewsArticle.objects.count(), 3)

    def test_conditional_headers_sent_when_validators_exist(self):
        self.source.etag = '"v1"'
        self.source.last_modified = 'Wed, 29 Oct 2026 10:00:00 GMT'
        self.source.save()
        with patch.object(
            NewsScraper,
            'make_request',
            return_value=_response(FEED_A),
        ) as mock_request:
            self.scraper.scrape_portal(self.source.feed_url)
        headers = mock_request.call_args.kwargs['headers']
        self.assertEqual(headers['If-None-Match'], '"v1"')
        self.assertEqual(
            headers['If-Modified-Since'],
            'Wed, 29 Oct 2026 10:00:00 GMT',
        )
        # The browser defaults ride along — make_request would
        # otherwise drop the User-Agent.
        self.assertIn('User-Agent', headers)

    def test_no_conditional_headers_without_validators(self):
        with patch.object(
            NewsScraper,
            'make_request',
            return_value=_response(FEED_A),
        ) as mock_request:
            self.scraper.scrape_portal(self.source.feed_url)
        headers = mock_request.call_args.kwargs['headers']
        self.assertNotIn('If-None-Match', headers)
        self.assertNotIn('If-Modified-Since', headers)

    def test_fresh_run_sends_no_conditional_headers(self):
        """--fresh is the escape hatch: the runner's fresh flag
        suppresses conditional headers so a deliberately
        re-scraped feed is re-parsed instead of 304ing."""
        self.source.etag = '"v1"'
        self.source.last_modified = 'Wed, 29 Oct 2026 10:00:00 GMT'
        self.source.save()
        runner = ScrapeJobRunner(slug='news.feeds', fresh=True)
        scraper = NewsScraper(runner=runner)
        scraper._active_source = self.source
        response = _response(FEED_A, headers={'ETag': '"v2"'})
        with patch.object(
            NewsScraper, 'make_request', return_value=response
        ) as mock_request:
            scraper.scrape_portal(self.source.feed_url)
        headers = mock_request.call_args.kwargs['headers']
        self.assertNotIn('If-None-Match', headers)
        self.assertNotIn('If-Modified-Since', headers)
        # Fresh 200 validators are still stored for the next
        # (non-fresh) poll.
        self.source.refresh_from_db()
        self.assertEqual(self.source.etag, '"v2"')

    def test_error_response_does_not_store_validators(self):
        """A 403/404 error page can carry its own ETag — storing
        it would wrongly 304 the feed on the next poll."""
        response = _response(
            b'forbidden',
            status=403,
            headers={
                'ETag': '"err"',
                'Last-Modified': 'Thu, 30 Oct 2026 08:00:00 GMT',
            },
        )
        with patch.object(
            NewsScraper, 'make_request', return_value=response
        ):
            self.scraper.scrape_portal(self.source.feed_url)
        self.source.refresh_from_db()
        self.assertIsNone(self.source.etag)
        self.assertIsNone(self.source.last_modified)

    def test_oversized_validators_are_truncated(self):
        """A >200-char ETag/Last-Modified must be truncated to
        the field max_length, not DataError on save."""
        long_etag = '"' + 'x' * 300 + '"'
        long_modified = 'M' * 300
        response = _response(
            FEED_A,
            headers={
                'ETag': long_etag,
                'Last-Modified': long_modified,
            },
        )
        with patch.object(
            NewsScraper, 'make_request', return_value=response
        ):
            self.scraper.scrape_portal(self.source.feed_url)
        self.source.refresh_from_db()
        self.assertEqual(self.source.etag, long_etag[:200])
        self.assertEqual(
            self.source.last_modified, long_modified[:200]
        )

    def test_feed_url_change_clears_validators(self):
        """An admin feed_url edit points the source at a
        different resource — the old resource's validators must
        not be sent or a legitimate 304 would skip parsing."""
        self.source.etag = '"v1"'
        self.source.last_modified = 'Wed, 29 Oct 2026 10:00:00 GMT'
        self.source.save()
        self.source.feed_url = 'https://a.lv/other-rss'
        self.source.save()
        self.source.refresh_from_db()
        self.assertIsNone(self.source.etag)
        self.assertIsNone(self.source.last_modified)

    def test_unchanged_feed_url_keeps_validators(self):
        self.source.etag = '"v1"'
        self.source.last_modified = 'Wed, 29 Oct 2026 10:00:00 GMT'
        self.source.save()
        self.source.name = 'Renamed'
        self.source.save()
        self.source.refresh_from_db()
        self.assertEqual(self.source.etag, '"v1"')
        self.assertEqual(
            self.source.last_modified,
            'Wed, 29 Oct 2026 10:00:00 GMT',
        )

    def test_second_pass_inserts_nothing_only_bumps_last_seen(self):
        with patch.object(
            NewsScraper,
            'make_request',
            return_value=_response(FEED_A),
        ):
            articles = self.scraper.scrape_portal(
                self.source.feed_url
            )
        self.scraper.create_or_update_resources(articles)
        self.assertEqual(NewsArticle.objects.count(), 3)
        old_seen = timezone.now() - timedelta(days=1)
        NewsArticle.objects.update(last_seen=old_seen)
        with (
            patch.object(
                NewsScraper,
                'make_request',
                return_value=_response(FEED_A),
            ),
            patch.object(
                NewsArticle.objects, 'bulk_create'
            ) as mock_create,
        ):
            articles = self.scraper.scrape_portal(
                self.source.feed_url
            )
        self.assertFalse(articles)
        mock_create.assert_not_called()
        self.assertEqual(NewsArticle.objects.count(), 3)
        for article in NewsArticle.objects.all():
            self.assertGreater(article.last_seen, old_seen)


class DryRunTests(TestCase):
    """--dry-run on an unseeded DB: the unsaved NEWS_FEEDS/TOPICS
    fallback objects must not reach related-object filters and
    nothing may be written."""

    def test_dry_run_unseeded_db_writes_nothing(self):
        scraper = NewsScraper(dry_run=True)
        scraper._active_source = scraper._enabled_sources()[0]
        results = scraper.parse_results(_response(FEED_A))
        articles = scraper.initiate_resources(results)
        scraper.create_or_update_resources(articles)
        self.assertEqual(NewsArticle.objects.count(), 0)


class SourceFilterTests(TestCase):
    """--source narrows the pass but must not deactivate the
    other feeds' ScrapeJobItem rows."""

    def setUp(self):
        self.a = _source('a')
        self.b = _source('b')

    def test_source_run_keeps_other_items_active(self):
        runner = ScrapeJobRunner(slug='news.feeds')
        scraper = NewsScraper(runner=runner, source_slug='a')
        urls = list(scraper.get_search_urls())
        self.assertEqual(urls, ['https://a.lv/rss'])
        items = {
            i.key: i.is_active
            for i in ScrapeJobItem.objects.all()
        }
        self.assertEqual(items, {'a': True, 'b': True})

    def test_unknown_source_deactivates_nothing(self):
        runner = ScrapeJobRunner(slug='news.feeds')
        scraper = NewsScraper(runner=runner, source_slug='nope')
        self.assertEqual(list(scraper.get_search_urls()), [])
        self.assertEqual(
            ScrapeJobItem.objects.filter(is_active=True).count(), 2
        )


class ScrapeNewsCommandTests(TestCase):
    """scrape_news --source: a filtered run finishes PARTIAL,
    leaves the other feeds' items pending and neither satisfies
    nor trips the cycle gate."""

    @patch.object(
        NewsScraper, 'make_request',
        return_value=_response(FEED_A),
    )
    def test_source_run_leaves_other_items_pending(self, _mock):
        call_command('scrape_news', source='lsm', stdout=StringIO())
        run = ScrapeJobRun.objects.get()
        # PARTIAL — a filtered run must not satisfy the cycle's
        # SUCCESS gate.
        self.assertEqual(run.status, ScrapeJobRun.PARTIAL)
        done_keys = set(
            ScrapeJobRunItem.objects.filter(
                run=run, status=ScrapeJobRunItem.DONE,
            ).values_list('item__key', flat=True)
        )
        self.assertEqual(done_keys, {'lsm'})
        self.assertFalse(cycle_scrape_exists('news.feeds'))
        self.assertTrue(
            NewsArticle.objects.filter(source__slug='lsm').exists()
        )
        # The follow-up full run is not refused — it resumes and
        # scrapes the remaining feeds.
        out = StringIO()
        call_command('scrape_news', stdout=out)
        self.assertNotIn('skipping', out.getvalue())
        self.assertTrue(
            NewsArticle.objects.filter(source__slug='delfi').exists()
        )

    @patch.object(
        NewsScraper, 'make_request',
        return_value=_response(FEED_A),
    )
    def test_source_run_after_full_run_not_refused(self, _mock):
        call_command('scrape_news', stdout=StringIO())
        self.assertTrue(cycle_scrape_exists('news.feeds'))
        out = StringIO()
        call_command('scrape_news', source='lsm', stdout=out)
        # A targeted re-scrape bypasses the cycle gate and
        # actually re-fetches the feed even though its item was
        # already DONE this cycle.
        self.assertNotIn('skipping', out.getvalue())
        latest = ScrapeJobRun.objects.latest('id')
        self.assertTrue(
            ScrapeJobRunItem.objects.filter(
                run=latest, item__key='lsm',
                status=ScrapeJobRunItem.DONE,
            ).exists()
        )


class ClassificationTests(TestCase):
    def setUp(self):
        self.funding = NewsTopic.objects.create(
            slug='government-funding',
            name='Valsts finansējums',
            weight=1.3,
            keywords=['budžets', 'finansējums', 'ES fondi'],
        )
        self.politics = NewsTopic.objects.create(
            slug='politics',
            name='Politika',
            weight=1.0,
            keywords=['Saeima', 'ministrs'],
        )
        self.topics = NewsTopic.objects.filter(is_enabled=True)

    def test_budget_article_maps_to_funding(self):
        topic = classify_topic(
            'Saeima apstiprina 2027. gada valsts budžetu',
            'ES fondi un finansējums.',
            self.topics,
        )
        self.assertEqual(topic, self.funding)

    def test_unrelated_text_returns_none(self):
        topic = classify_topic(
            'Sporta klubs svin uzvaru',
            'Aizraujoša spēle.',
            self.topics,
        )
        self.assertIsNone(topic)

    def test_single_lead_hit_below_min_score_stays_null(self):
        # A lone lead hit scores 1 < MIN_TOPIC_SCORE — the
        # article stays untopicked.
        topic = classify_topic(
            'Mūzikas festivāls noslēdzas',
            'Saeima debatēs par likumu.',
            self.topics,
        )
        self.assertIsNone(topic)

    def test_single_title_hit_reaches_min_score(self):
        # The same keyword inside the title scores 2 (hit +
        # title bonus) — enough to classify on its own.
        topic = classify_topic(
            'Saeima debatēs par likumu',
            'Mūzikas festivāls noslēdzas.',
            self.topics,
        )
        self.assertEqual(topic, self.politics)


def _article(source, title, topic=None, published=None, **kw):
    return NewsArticle.objects.create(
        source=source,
        external_id=hashlib.sha256(
            f'{source.slug}:{title}'.encode()
        ).hexdigest()[:32],
        link=f'https://{source.slug}.lv/{abs(hash(title))}',
        title=title,
        published_at=published or timezone.now(),
        topic=topic,
        **kw,
    )


class ClusteringTests(TestCase):
    def setUp(self):
        self.a = _source('a')
        self.b = _source('b')
        self.now = timezone.now()

    def test_same_story_clusters_across_outlets(self):
        a1 = _article(
            self.a, 'Saeima pieņem 2027. gada budžetu',
            published=self.now,
        )
        a2 = _article(
            self.b,
            'Valdības budžets 2027. gadam apstiprināts Saeimā',
            published=self.now,
        )
        a3 = _article(
            self.a, 'Sporta klubs svin uzvaru čempionātā',
            published=self.now,
        )
        stats = link_unmatched_articles(days=2)
        a1.refresh_from_db()
        a2.refresh_from_db()
        a3.refresh_from_db()
        self.assertIsNotNone(a1.story_id)
        self.assertEqual(a1.story_id, a2.story_id)
        self.assertEqual(a1.story_match_status, 'auto')
        self.assertEqual(a2.story_match_status, 'auto')
        self.assertNotEqual(a3.story_id, a1.story_id)
        self.assertEqual(stats['linked'], 1)
        self.assertEqual(stats['new_stories'], 2)
        # The clustered story counts both outlets.
        story = a1.story
        story.refresh_from_db()
        self.assertEqual(story.source_count, 2)

    def test_generic_date_stems_do_not_auto_merge(self):
        # Shared stems are only 'budž' + 'gada' — a topic word
        # plus year boilerplate. The Jaccard clears the auto
        # bar, but auto-merge also requires a second
        # substantive shared stem, so the article starts its
        # own story instead of gluing state vs municipal
        # budgets together.
        a1 = _article(
            self.a, 'Valsts budžets 2027. gadam',
            published=self.now,
        )
        a2 = _article(
            self.b, 'Pašvaldību budžets 2027. gadam',
            published=self.now,
        )
        link_unmatched_articles(days=2)
        a1.refresh_from_db()
        a2.refresh_from_db()
        self.assertEqual(a2.story_match_status, 'auto')
        self.assertNotEqual(a2.story_id, a1.story_id)

    def test_looser_threshold_merges_borderline_titles(self):
        # Jaccard ~0.43 with three substantive shared stems —
        # under the old 0.45 bar this queued for admin review;
        # the candidate band is gone, so it auto-merges.
        a1 = _article(
            self.a, 'Saeima pieņem jauno budžetu',
            published=self.now,
        )
        a2 = _article(
            self.b,
            'Saeima apspriež jauno budžetu komisijas sēdē',
            published=self.now,
        )
        link_unmatched_articles(days=2)
        a1.refresh_from_db()
        a2.refresh_from_db()
        self.assertEqual(a2.story_id, a1.story_id)
        self.assertEqual(a2.story_match_status, 'auto')

    def test_old_articles_are_out_of_scope(self):
        old = _article(
            self.a, 'Ļoti vecs virsraksts par neko',
            published=self.now - timedelta(days=30),
        )
        stats = link_unmatched_articles(days=2)
        old.refresh_from_db()
        self.assertIsNone(old.story_id)
        self.assertEqual(stats['new_stories'], 0)

    def test_candidate_member_does_not_inflate_story(self):
        # 'candidate' links are no longer produced, but legacy
        # rows exist — an unreviewed member must not inflate
        # the story's confirmed-coverage counts.
        a1 = _article(
            self.a, 'Valsts budžets 2027. gadam',
            published=self.now,
        )
        link_unmatched_articles(days=2)
        a1.refresh_from_db()
        story = a1.story
        _article(
            self.b, 'Pašvaldību budžets 2027. gadam',
            published=self.now, story=story,
            story_match_status='candidate',
        )
        _refresh_story(story)
        story.refresh_from_db()
        self.assertEqual(story.source_count, 1)

    def test_auto_merge_uses_best_qualifying_member_title(self):
        # The argmax member title scores 0.60 but shares only
        # one substantive stem (the rest is 'gada'/'gadu' date
        # boilerplate); a second member title scores 0.50 with
        # three substantive shared stems — that one clears the
        # auto-merge bar, so the link is 'auto', not rejected
        # on the argmax title alone.
        story = NewsStory.objects.create(
            title='Budžetu stāsts',
            published_date=timezone.localdate(),
        )
        c = _source('c')
        _article(
            self.a, 'Budžets 2027. gada un 2028. gadu',
            published=self.now, story=story,
            story_match_status='auto',
        )
        _article(
            self.b, 'Pašvaldību budžets apstiprināts Saeimā',
            published=self.now, story=story,
            story_match_status='manual',
        )
        article = _article(
            c,
            'Pašvaldību budžets 2027. gada un 2028. gadu '
            'apstiprināts',
            published=self.now,
        )
        link_unmatched_articles(days=2)
        article.refresh_from_db()
        self.assertEqual(article.story_id, story.id)
        self.assertEqual(article.story_match_status, 'auto')

    def test_stopword_only_title_gets_own_story(self):
        # The title stems to nothing (all stopwords) so it can
        # never match — it gets its own story instead of staying
        # 'unmatched' and being rescanned every run.
        article = _article(
            self.a, 'Un ir tas vai bet',
            published=self.now,
        )
        stats = link_unmatched_articles(days=2)
        article.refresh_from_db()
        self.assertIsNotNone(article.story_id)
        self.assertEqual(article.story_match_status, 'auto')
        self.assertEqual(stats['new_stories'], 1)

    def test_story_topic_rederived_as_members_accrue(self):
        # a1 is untopicked, so the story starts NULL; when a2 —
        # a war-tagged member — auto-merges on the next pass,
        # the refresh re-derives the topic instead of keeping
        # the creation-time NULL.
        war = NewsTopic.objects.create(
            slug='war', name='Karš', weight=1.1, keywords=[],
        )
        a1 = _article(
            self.a, 'Krievija izsviež raķetes pret pilsētu',
            published=self.now,
        )
        link_unmatched_articles(days=2)
        a1.refresh_from_db()
        story = a1.story
        self.assertIsNone(story.topic_id)
        a2 = _article(
            self.b,
            'Krievija izsviež raķetes pret pilsētu atkal',
            published=self.now, topic=war,
        )
        link_unmatched_articles(days=2)
        a2.refresh_from_db()
        story.refresh_from_db()
        self.assertEqual(a2.story_id, story.id)
        self.assertEqual(a2.story_match_status, 'auto')
        self.assertEqual(story.topic_id, war.id)

    def test_story_topic_ignores_candidate_members(self):
        # A 'candidate' member's tag must not vote — the story
        # topic stays NULL while the link is unreviewed.
        war = NewsTopic.objects.create(
            slug='war', name='Karš', weight=1.1, keywords=[],
        )
        a1 = _article(
            self.a, 'Valsts budžets 2027. gadam',
            published=self.now,
        )
        link_unmatched_articles(days=2)
        a1.refresh_from_db()
        story = a1.story
        _article(
            self.b, 'Pašvaldību budžets 2027. gadam',
            published=self.now, story=story,
            story_match_status='candidate', topic=war,
        )
        _refresh_story(story)
        story.refresh_from_db()
        self.assertIsNone(story.topic_id)

    def test_story_topic_modal_with_pk_tie_break(self):
        # Confirmed members vote on the story topic: a 1-1 tie
        # resolves to the lowest topic pk, and a third member
        # breaks the tie outright — NULL members never vote.
        t1 = NewsTopic.objects.create(
            slug='one', name='Tēma 1', keywords=[],
        )
        t2 = NewsTopic.objects.create(
            slug='two', name='Tēma 2', keywords=[],
        )
        story = NewsStory.objects.create(
            title='Stāsts', published_date=timezone.localdate(),
        )
        _article(
            self.a, 'Stāsts', topic=t2, story=story,
            story_match_status='auto',
        )
        _article(
            self.b, 'Stāsts', topic=t1, story=story,
            story_match_status='auto',
        )
        _refresh_story(story)
        self.assertEqual(story.topic_id, t1.id)
        c = _source('c')
        _article(
            c, 'Stāsts', topic=t2, story=story,
            story_match_status='auto',
        )
        _refresh_story(story)
        self.assertEqual(story.topic_id, t2.id)


class DigestTests(TestCase):
    def setUp(self):
        self.a = _source('a')
        self.b = _source('b')
        self.topic = NewsTopic.objects.create(
            slug='politics', name='Politika', weight=1.0,
            keywords=['Saeima'],
        )
        self.today = timezone.localdate()

    _UNSET = object()

    def _story(self, title, score, topic=_UNSET, source=None):
        if topic is self._UNSET:
            topic = self.topic
        story = NewsStory.objects.create(
            title=title,
            topic=topic,
            published_date=self.today,
            importance_score=score,
            source_count=1,
        )
        _article(
            source or self.a, title, topic=topic,
            story=story, story_match_status='auto',
        )
        return story

    def test_top_n_unique_and_skips_untopicked(self):
        self._story('Ziņa viens', 5.0)
        self._story('Ziņa divi', 4.0)
        self._story('Ziņa trīs', 3.0)
        self._story('Bez tēmas', 99.0, topic=None)
        result = build_digest(self.today, top_n=2)
        self.assertEqual(len(result['items']), 2)
        headlines = [h for _, h, _ in result['items']]
        self.assertEqual(headlines, ['Ziņa viens', 'Ziņa divi'])
        self.assertNotIn('Bez tēmas', headlines)

    def test_rebuild_is_idempotent(self):
        self._story('Ziņa viens', 5.0)
        build_digest(self.today, top_n=5)
        build_digest(self.today, top_n=5)
        self.assertEqual(NewsDigest.objects.count(), 1)
        digest = NewsDigest.objects.get()
        self.assertEqual(digest.items.count(), 1)
        self.assertEqual(digest.items.first().rank, 1)

    def test_rationale_lists_outlets(self):
        story = self._story('Ziņa viens', 5.0, source=self.a)
        _article(
            self.b, 'Ziņa viens (B)', topic=self.topic,
            story=story, story_match_status='auto',
        )
        story.source_count = 2
        story.save()
        result = build_digest(self.today, top_n=5)
        _, _, rationale = result['items'][0]
        self.assertIn('2 outlets', rationale)
        self.assertIn('a', rationale)
        self.assertIn('b', rationale)

    def test_candidate_member_excluded_from_rationale(self):
        story = self._story('Ziņa viens', 5.0, source=self.a)
        _article(
            self.b, 'Ziņa viens (B)', topic=self.topic,
            story=story, story_match_status='candidate',
        )
        result = build_digest(self.today, top_n=5)
        _, _, rationale = result['items'][0]
        # The 'candidate' link awaits admin review — it must not
        # count as coverage. Singular count is not pluralized.
        self.assertEqual(rationale, '1 outlet: a')

    def test_all_candidate_story_excluded_from_digest(self):
        story = NewsStory.objects.create(
            title='Tikai kandidāti', topic=self.topic,
            published_date=self.today,
            importance_score=99.0, source_count=2,
        )
        _article(
            self.a, 'Tikai kandidāti', topic=self.topic,
            story=story, story_match_status='candidate',
        )
        result = build_digest(self.today, top_n=5)
        self.assertEqual(result['items'], [])

    def test_multi_source_untopicked_story_is_eligible(self):
        # A NULL-topic story with multi-outlet coverage is
        # itself strong importance evidence — it must not lose
        # the digest to a weaker keyword-matched story.
        story = self._story('Bez tēmas', 3.0, topic=None)
        _article(
            self.b, 'Bez tēmas (B)', topic=None,
            story=story, story_match_status='auto',
        )
        story.source_count = 2
        story.save()
        result = build_digest(self.today, top_n=5)
        headlines = [h for _, h, _ in result['items']]
        self.assertEqual(headlines, ['Bez tēmas'])

    def test_single_source_untopicked_story_stays_excluded(self):
        # One outlet and no topic is still noise — the digest
        # keeps it out even at the top importance score.
        self._story('Bez tēmas', 99.0, topic=None)
        result = build_digest(self.today, top_n=5)
        self.assertEqual(result['items'], [])

    def test_detail_page_renders_confirmed_members_only(self):
        story = self._story('Ziņa viens', 5.0, source=self.a)
        cand = _article(
            self.b, 'Kandidāts (B)', topic=self.topic,
            story=story, story_match_status='candidate',
        )
        build_digest(self.today, top_n=5)
        response = self.client.get(
            f'/api/news/digests/{self.today.isoformat()}/'
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()['items']
        self.assertEqual(items[0]['headline'], 'Ziņa viens')
        titles = [
            article['title']
            for item in items
            for article in item['articles']
        ]
        self.assertNotIn(cand.title, titles)


class DigestGoogleTaskTests(TestCase):
    """The build -> Google task hook: insert body, list
    resolution, rebuild dedup and never-raise failure paths."""

    def setUp(self):
        self.a = _source('gta')
        self.topic = NewsTopic.objects.create(
            slug='politics', name='Politika', weight=1.0,
            keywords=['Saeima'],
        )
        self.today = timezone.localdate()
        self.user = get_user_model().objects.create_user('owner')
        self._cfg = override_settings(
            GOOGLE_OAUTH_CLIENT_JSON='{}',
            GOOGLE_TASKS_USERNAME='owner',
            GOOGLE_TASKS_LIST_TITLE='News',
        )
        self._cfg.enable()
        self.addCleanup(self._cfg.disable)

    def _story(self, title='Ziņa viens', score=5.0):
        story = NewsStory.objects.create(
            title=title,
            topic=self.topic,
            published_date=self.today,
            importance_score=score,
            source_count=1,
        )
        _article(
            self.a, title, topic=self.topic,
            story=story, story_match_status='auto',
        )
        return story

    def _service(self, lists=None):
        service = Mock()
        service.tasklists.return_value.list\
            .return_value.execute.return_value = {
                'items': (
                    [{'id': 'l1', 'title': 'News'}]
                    if lists is None else lists
                ),
            }
        service.tasklists.return_value.insert\
            .return_value.execute.return_value = {'id': 'l1'}
        service.tasks.return_value.insert\
            .return_value.execute.return_value = {'id': 't1'}
        return service

    def _build(self, **kwargs):
        service = kwargs.pop('service', self._service())
        with (
            patch(
                'news.tasks.get_user_credentials',
                return_value=kwargs.pop('creds', Mock()),
            ),
            patch('news.tasks.build', return_value=service),
        ):
            result = build_digest(self.today, **kwargs)
        return result, service

    def test_insert_body_title_notes_no_due(self):
        self._story()
        result, service = self._build()
        insert = service.tasks.return_value.insert
        insert.assert_called_once()
        body = insert.call_args.kwargs['body']
        date_str = self.today.isoformat()
        self.assertEqual(body['title'], f'News digest {date_str}')
        self.assertNotIn('due', body)
        notes = body['notes']
        self.assertIn(f'/news/{date_str}/', notes)
        self.assertIn('1. Ziņa viens', notes)
        # Each headline carries the preferred outlet's link.
        self.assertIn('(https://gta.lv/', notes)
        link = NewsDigestTask.objects.get()
        self.assertEqual(link.status, 'created')
        self.assertEqual(link.task_id, 't1')
        self.assertEqual(link.task_list_id, 'l1')

    def test_list_auto_created_when_absent(self):
        self._story()
        _, service = self._build(service=self._service(lists=[]))
        service.tasklists.return_value.insert.assert_called_once_with(
            body={'title': 'News'}
        )
        link = NewsDigestTask.objects.get()
        self.assertEqual(link.task_list_id, 'l1')

    def test_existing_list_reused_case_insensitive(self):
        self._story()
        _, service = self._build(
            service=self._service(
                lists=[{'id': 'l9', 'title': 'news'}]
            )
        )
        service.tasklists.return_value.insert.assert_not_called()
        insert = service.tasks.return_value.insert
        self.assertEqual(insert.call_args.kwargs['tasklist'], 'l9')

    def test_rebuild_does_not_duplicate_task(self):
        self._story()
        _, service = self._build()
        self._build(service=service)
        service.tasks.return_value.insert.assert_called_once()

    def test_dry_run_touches_nothing_remote(self):
        self._story()
        result, service = self._build(dry_run=True)
        self.assertEqual(len(result['items']), 1)
        service.tasks.return_value.insert.assert_not_called()
        self.assertEqual(NewsDigestTask.objects.count(), 0)

    def test_missing_creds_failed_row_digest_intact(self):
        self._story()
        self._build(creds=None)
        digest = NewsDigest.objects.get()
        self.assertEqual(digest.items.count(), 1)
        link = NewsDigestTask.objects.get()
        self.assertEqual(link.status, 'failed')
        self.assertIn('google/login', link.error)

    def test_failed_row_retried_on_rebuild(self):
        self._story()
        self._build(creds=None)
        _, service = self._build()
        service.tasks.return_value.insert.assert_called_once()
        link = NewsDigestTask.objects.get()
        self.assertEqual(link.status, 'created')
        self.assertEqual(link.task_id, 't1')

    def test_feature_disabled_no_link_row(self):
        self._story()
        service = self._service()
        with (
            override_settings(
                GOOGLE_OAUTH_CLIENT_JSON='',
                GOOGLE_TASKS_USERNAME='',
            ),
            patch('news.tasks.build', return_value=service) as b,
        ):
            build_digest(self.today)
        b.assert_not_called()
        self.assertEqual(NewsDigestTask.objects.count(), 0)


class StemClassificationTests(TestCase):
    """Inflected Latvian must still hit the base-form keyword —
    the shared stemmer collapses 'Saeimas'/'Saeima' onto the
    'saei' stem; multi-word keywords need all their stems."""

    def setUp(self):
        self.funding = NewsTopic.objects.create(
            slug='government-funding',
            name='Valsts finansējums',
            weight=1.3,
            keywords=[
                'budžets', 'finansējums', 'ES fondi',
                'Eiropas Savienības fondi',
            ],
        )
        self.politics = NewsTopic.objects.create(
            slug='politics',
            name='Politika',
            weight=1.0,
            keywords=['Saeima', 'valdība', 'deputāts'],
        )
        self.economics = NewsTopic.objects.create(
            slug='economics',
            name='Ekonomika',
            weight=1.2,
            keywords=['tarifi', 'elektroenerģija'],
        )
        # Topic order decides score ties — funding first so the
        # 'budž' vs 'vald' tie below resolves to funding.
        self.topics = [self.funding, self.politics, self.economics]

    def test_inflected_saeima_hits_politics(self):
        topic = classify_topic(
            'Saeimas deputāti balso par likumu',
            '',
            self.topics,
        )
        self.assertEqual(topic, self.politics)

    def test_inflected_budget_hits_funding(self):
        topic = classify_topic(
            'Valdības budžeta izmaiņas',
            '',
            self.topics,
        )
        self.assertEqual(topic, self.funding)

    def test_inflected_energy_hits_economics(self):
        topic = classify_topic(
            'Elektroenerģijas tarifi pieaugs',
            '',
            self.topics,
        )
        self.assertEqual(topic, self.economics)

    def test_unrelated_title_returns_none(self):
        topic = classify_topic(
            'Dziedātāja izlaiž jaunu albumu',
            'Koncertu tūre sākas rudenī.',
            self.topics,
        )
        self.assertIsNone(topic)

    def test_multiword_keyword_all_stems_present(self):
        # 'ES fondi' stems to {es, fond} — both appear inflected
        # in the title; 'Eiropas Savienības fondi' only partially
        # overlaps and does not hit.
        topic = classify_topic(
            'ES fondu līdzekļi pašvaldībām',
            '',
            self.topics,
        )
        self.assertEqual(topic, self.funding)

    def test_multiword_keyword_partial_stems_miss(self):
        # Only 'fond' is present — 'ES fondi' requires 'es' too.
        topic = classify_topic(
            'Fondu pārvalde pārskata prioritātes',
            '',
            self.topics,
        )
        self.assertIsNone(topic)

    def test_title_hits_weigh_double(self):
        # economics: 'tarifi' in the title (2 points); politics:
        # 'Saeima' only in the lead (1 point) — the title hit
        # wins outright rather than tying.
        topic = classify_topic(
            'Tarifi pieaugs',
            'Saeima debatēs.',
            self.topics,
        )
        self.assertEqual(topic, self.economics)


class SeedKeywordTests(TestCase):
    """Regression tests against the TOPICS seed lists themselves
    — the false-positive/miss curation lives in the data, so it
    is exercised through unsaved NewsTopic instances."""

    def setUp(self):
        self.topics = [NewsTopic(**t) for t in TOPICS]

    def test_rakete_headline_classifies_as_war(self):
        # 'raķeš*' could not reach the nominative 'raķete'/
        # 'raķetes' — the 'raķet*' prefix covers it.
        topic = classify_topic(
            'Krievija izsviež raķetes uz pilsētu',
            '',
            self.topics,
        )
        self.assertIsNotNone(topic)
        self.assertEqual(topic.slug, 'war')

    def test_finansu_phrase_not_government_funding(self):
        # Plain 'finansējums' stemmed to 'fina' and matched any
        # 'finanšu …' phrase; 'finansējum*' must not.
        topic = classify_topic(
            'Finanšu prasmes: ko māca skolās bērniem',
            '',
            self.topics,
        )
        self.assertIsNone(topic)


class ReclassifyCommandTests(TestCase):
    def setUp(self):
        self.source = _source('a')
        self.politics = NewsTopic.objects.create(
            slug='politics', name='Politika', weight=2.0,
            keywords=['Saeima', 'deputāts'],
        )

    def _clustered_article(self):
        article = _article(
            self.source, 'Saeimas deputāti pieņem likumu',
            published=timezone.now(),
        )
        link_unmatched_articles(days=2)
        article.refresh_from_db()
        return article

    def test_dry_run_writes_nothing(self):
        article = self._clustered_article()
        story = article.story
        old_importance = story.importance_score
        call_command(
            'reclassify_news_articles',
            '--dry-run',
            stdout=StringIO(),
        )
        article.refresh_from_db()
        story.refresh_from_db()
        self.assertIsNone(article.topic_id)
        self.assertIsNone(story.topic_id)
        self.assertEqual(story.importance_score, old_importance)

    def test_run_flips_topic_and_refreshes_story(self):
        article = self._clustered_article()
        story = article.story
        self.assertIsNone(story.topic_id)
        call_command('reclassify_news_articles', stdout=StringIO())
        article.refresh_from_db()
        story.refresh_from_db()
        self.assertEqual(article.topic_id, self.politics.id)
        # The story adopts the member topic and its refreshed
        # importance uses that weight (1 source x 2.0 x 1.0).
        self.assertEqual(story.topic_id, self.politics.id)
        self.assertEqual(story.importance_score, 2.0)

    def test_untopicked_story_with_topiced_members_refreshes(self):
        # Defect: a story created untopicked keeps topic=NULL
        # even after members are retagged by the scraper's
        # update path. No member's topic changes here, so the
        # story must reach _refresh_story off the scanned-member
        # bookkeeping alone (--all scans topiced articles).
        story = NewsStory.objects.create(
            title='Ziņa', published_date=timezone.localdate(),
        )
        _article(
            self.source, 'Saeimas deputāti pieņem likumu',
            topic=self.politics, story=story,
            story_match_status='auto',
        )
        call_command(
            'reclassify_news_articles', '--all', stdout=StringIO(),
        )
        story.refresh_from_db()
        self.assertEqual(story.topic_id, self.politics.id)
        self.assertEqual(story.importance_score, 2.0)

    def test_all_flag_reclassifies_assigned_articles(self):
        other = NewsTopic.objects.create(
            slug='other', name='Cits', keywords=['zzzz'],
        )
        article = _article(
            self.source, 'Saeimas deputāti pieņem likumu',
            topic=other, published=timezone.now(),
        )
        # Default scope touches untopicked articles only.
        call_command('reclassify_news_articles', stdout=StringIO())
        article.refresh_from_db()
        self.assertEqual(article.topic_id, other.id)
        call_command(
            'reclassify_news_articles', '--all', stdout=StringIO(),
        )
        article.refresh_from_db()
        self.assertEqual(article.topic_id, self.politics.id)


class KeywordMarkerTests(TestCase):
    """Marker syntax: '=w' = exact token, 'w*' = token prefix,
    plain 'w' = 4-char stem (news.classification docstring)."""

    def _topic(self, keywords):
        return NewsTopic.objects.create(
            slug='t', name='T', weight=1.0, keywords=keywords,
        )

    def test_exact_marker_requires_literal_token(self):
        topic = self._topic(['=eiro'])
        hit = classify_topic('Eiro kurss stabilizējas', '', [topic])
        miss = classify_topic('Eirozona paplašinās', '', [topic])
        self.assertEqual(hit, topic)
        self.assertIsNone(miss)

    def test_prefix_marker_hits_inflection_family_only(self):
        topic = self._topic(['premjer*'])
        hit = classify_topic('Premjeru amatā apstiprina', '', [topic])
        miss = classify_topic('Premiju par sniegumu', '', [topic])
        self.assertEqual(hit, topic)
        self.assertIsNone(miss)

    def test_exact_marker_does_not_hit_stem_family(self):
        # '=Latvenergo' is a proper noun — 'Latvijas' shares the
        # 'latv' stem and must not match.
        topic = self._topic(['=Latvenergo'])
        hit = classify_topic(
            'Latvenergo peļņa pieaug', '', [topic],
        )
        miss = classify_topic(
            'Latvijas hokeja izlase zaudē', '', [topic],
        )
        self.assertEqual(hit, topic)
        self.assertIsNone(miss)

    def test_marker_inside_multiword_keyword(self):
        topic = self._topic(['aizsardzības ministrij*'])
        hit = classify_topic(
            'Aizsardzības ministrija apstiprina plānu',
            '',
            [topic],
        )
        miss = classify_topic(
            'Aizsardzības minimums sasniegts', '', [topic],
        )
        self.assertEqual(hit, topic)
        self.assertIsNone(miss)

    def test_title_double_count_applies_to_marked_specs(self):
        topic = self._topic(['grant*'])
        in_title = classify_topic('Grantu konkursā uzvar', '', [topic])
        # A lone lead hit is below MIN_TOPIC_SCORE — the title
        # bonus or a second keyword is what reaches the gate.
        in_lead = classify_topic('Ziņa', 'Grantu konkursā.', [topic])
        two_hits = classify_topic(
            'Ziņa', 'Grantu konkursā.',
            [NewsTopic(keywords=['grant*', 'konkurs*'])],
        )
        self.assertEqual(in_title, topic)
        self.assertIsNone(in_lead)
        self.assertIsNotNone(two_hits)


class CuratedSeedKeywordTests(TestCase):
    """Regression tests for the PR-47 review false positives on
    the real TOPICS seed list — 4-char stems turned keywords
    into near-universal matchers ('Latvenergo'->'latv' hit
    'Latvijas', 'līdzfinansējums'->'līdz' hit the preposition,
    'eiro'->'eiro' hit Eiropas*, 'eksports'->'eksp' hit
    eksperts, 'elektroauto'->'elek' hit elektrība,
    'premjers'->'prem' hit premija, 'partija'->'part' hit
    partneris, 'banka'->'bank' hit bankomāts/bankrotē,
    'grants'->'gran' hit granāta). The curated seeds must
    reject all of them and still hit real inflections.
    Round-2 additions cover satver/satvēra, ārlietās,
    valdzina, premjerlīga, inflamācija, koala, substrāts
    and ministrants."""

    def setUp(self):
        self.topics = [
            NewsTopic.objects.create(
                slug=t['slug'],
                name=t['name'],
                weight=t['weight'],
                keywords=t['keywords'],
            )
            for t in TOPICS
        ]
        self.by_slug = {t.slug: t for t in self.topics}

    def _topic(self, title, lead=''):
        return classify_topic(title, lead, self.topics)

    def test_latvijas_does_not_hit_latvenergo(self):
        self.assertIsNone(
            self._topic('Latvijas hokeja izlase zaudē')
        )

    def test_lidz_preposition_does_not_hit_funding(self):
        # 'līdzfinansējums'->'līdz' used to match the
        # preposition kept by drop_stopwords=False; the curated
        # 'līdzfinansējum*' prefix requires the 'līdzf' lead-in.
        self.assertIsNone(
            self._topic(
                'Dziedātāja izlaiž albumu',
                'Albums nonāks veikalos līdz rudenim.',
            )
        )

    def test_eiropas_does_not_hit_eiro(self):
        self.assertIsNone(
            self._topic('Eiropas čempionāts sākas')
        )

    def test_eksperti_does_not_hit_eksports(self):
        self.assertIsNone(
            self._topic('Eksperti brīdina par klimatu')
        )

    def test_premija_does_not_hit_premjers(self):
        self.assertIsNone(
            self._topic('Darbinieki saņem premiju par sniegumu')
        )

    def test_partneris_does_not_hit_partija(self):
        self.assertIsNone(
            self._topic('Uzņēmums atrod jaunu partneri')
        )

    def test_bankomats_does_not_hit_banka(self):
        self.assertIsNone(self._topic('Bankomāts nozagts'))

    def test_bankrote_does_not_hit_banka(self):
        self.assertIsNone(
            self._topic('Piegādātājs bankrotē pēc zaudējumiem')
        )

    def test_granata_does_not_hit_grants(self):
        self.assertIsNone(
            self._topic('Veca granāta atrasta pļavā')
        )

    def test_elektriba_alone_does_not_hit_funding(self):
        # Electricity prices are economics, not
        # government-funding — 'elektroauto'->'elek' used to
        # push every electricity article into funding.
        self.assertEqual(
            self._topic('Elektrības tarifi pieaugs'),
            self.by_slug['economics'],
        )

    def test_saeimas_deputati_hits_politics(self):
        self.assertEqual(
            self._topic('Saeimas deputāti balso par likumu'),
            self.by_slug['politics'],
        )

    def test_eksporta_hits_economics(self):
        self.assertEqual(
            self._topic('Eksporta apjomi sasniedz rekordu'),
            self.by_slug['economics'],
        )

    def test_premjeru_hits_politics(self):
        self.assertEqual(
            self._topic('Premjeru amatā apstiprina'),
            self.by_slug['politics'],
        )

    def test_elektroauto_subsidijas_hits_funding(self):
        self.assertEqual(
            self._topic('Elektroauto subsīdijas pagarinātas'),
            self.by_slug['government-funding'],
        )

    def test_latvenergo_hits_economics(self):
        self.assertEqual(
            self._topic('Latvenergo peļņa pieaug'),
            self.by_slug['economics'],
        )

    def test_banku_hits_economics(self):
        self.assertEqual(
            self._topic('Banku sektora peļņa'),
            self.by_slug['economics'],
        )

    def test_lidzfinansejums_hits_funding(self):
        self.assertEqual(
            self._topic('Projekts saņem līdzfinansējumu'),
            self.by_slug['government-funding'],
        )

    def test_partijas_hits_politics(self):
        self.assertEqual(
            self._topic('Partijas kongress nozīmē vadītāju'),
            self.by_slug['politics'],
        )

    # Round-2 residual collisions: stem/prefix conversions
    # must reject the lookalike tokens below while still
    # hitting the real inflection families.

    def test_satver_does_not_hit_satversme(self):
        # 'satver' (police seize) shares the 'satv' stem.
        self.assertIsNone(
            self._topic('Policija satver aizdomās turēto zagli')
        )

    def test_arlietas_does_not_hit_arlietu(self):
        # 'ārlietās' (outdoors) shares the 'ārli' stem.
        self.assertIsNone(
            self._topic('Pasākums notiks ārlietās')
        )

    def test_valdzina_does_not_hit_valdiba(self):
        self.assertIsNone(
            self._topic('Filma valdzina skatītājus')
        )

    def test_premjerliga_does_not_hit_premjers(self):
        self.assertIsNone(self._topic('Premjerlīgas spēle'))

    def test_inflamacija_does_not_hit_inflacija(self):
        self.assertIsNone(self._topic('Pacientam inflamācija'))

    def test_koala_does_not_hit_koalicija(self):
        self.assertIsNone(self._topic('Koala zooparkā'))

    def test_substrats_does_not_hit_subsidija(self):
        self.assertIsNone(self._topic('Substrāts augiem'))

    def test_ministrants_does_not_hit_ministrs(self):
        self.assertIsNone(
            self._topic('Ministrants dievkalpojumā')
        )

    def test_satversmes_hits_politics(self):
        self.assertEqual(
            self._topic('Satversmes tiesa skata lietu'),
            self.by_slug['politics'],
        )

    def test_arlietu_ministra_hits_diplomacy(self):
        # '=ārlietu' + '=ārlietu ministr*' moved to diplomacy
        # and outscore politics' '=ministra'.
        self.assertEqual(
            self._topic('Ārlietu ministra paziņojums'),
            self.by_slug['diplomacy'],
        )

    def test_valdibas_hits_politics(self):
        self.assertEqual(
            self._topic('Valdības sēde pieņem lēmumu'),
            self.by_slug['politics'],
        )

    def test_premjers_inflections_hit_politics(self):
        for title in (
            'Premjerministrs komentē reformu',
            'Premjers atklāj forumu',
            'Premjeru amatā apstiprina',
            'Premjeram jauns uzdevums',
        ):
            self.assertEqual(
                self._topic(title), self.by_slug['politics'],
            )

    def test_inflacijas_hits_economics(self):
        self.assertEqual(
            self._topic('Inflācijas temps pārsniedz prognozes'),
            self.by_slug['economics'],
        )

    def test_koalicijas_hits_politics(self):
        self.assertEqual(
            self._topic('Koalīcijas partneri vienojas'),
            self.by_slug['politics'],
        )

    def test_subsidijas_hits_funding(self):
        self.assertEqual(
            self._topic('Subsīdijas laukiem apstiprinātas'),
            self.by_slug['government-funding'],
        )

    def test_ministrs_ministru_hit_politics(self):
        for title in (
            'Ministrs komentē lēmumu',
            'Ministru apstiprina amatā',
        ):
            self.assertEqual(
                self._topic(title), self.by_slug['politics'],
            )

    # War/diplomacy seeds: positive hits plus the curated
    # near-miss tokens that must NOT reach them.

    def test_war_declensions_hit_war(self):
        for title in (
            'Karš Ukrainā turpinās',
            'Pēc kara sākas atjaunošana',
            'Krievija sāka karu pret kaimiņu',
            'Kaujas pie frontes smagās',
            'Raķešu uzbrukums Kijivā',
            'Droni apšauda pozīcijas',
            'Karavīri dotas nākamajā rotācijā',
        ):
            self.assertEqual(
                self._topic(title), self.by_slug['war'],
                msg=title,
            )

    def test_karuselis_does_not_hit_war(self):
        # 'karuselis' shares only the 'karu' prefix — exact
        # declension tokens, not 'kara*'/'karu*' prefixes.
        self.assertIsNone(
            self._topic('Jaunais karuselis priecē bērnus')
        )

    def test_karalis_does_not_hit_war(self):
        # Royals are not war — why the seeds are exact
        # tokens rather than a 'kara*' prefix.
        self.assertIsNone(
            self._topic('Karalis apmeklē jaunatnes svētkus')
        )

    def test_diplomacy_seeds_hit(self):
        for title in (
            'NATO samits Rīgā',
            'Jaunas sankcijas pret agresoru',
            'Vēstnieks iesniedz akreditācijas vēstules',
        ):
            self.assertEqual(
                self._topic(title), self.by_slug['diplomacy'],
                msg=title,
            )

    def test_partijas_kongress_not_diplomacy(self):
        # A party congress is domestic politics — the 'samit*'
        # summit family must not claim it.
        self.assertEqual(
            self._topic('Partijas kongress nozīmē vadītāju'),
            self.by_slug['politics'],
        )


class SeedSyncTests(TestCase):
    def setUp(self):
        call_command('seed_news_sources', stdout=StringIO())

    def _edit_politics(self):
        topic = NewsTopic.objects.get(slug='politics')
        topic.keywords = ['pielāgots']
        topic.weight = 9.9
        topic.save()
        return topic

    def test_seed_preserves_admin_edits(self):
        topic = self._edit_politics()
        call_command('seed_news_sources', stdout=StringIO())
        topic.refresh_from_db()
        self.assertEqual(topic.keywords, ['pielāgots'])
        self.assertEqual(topic.weight, 9.9)

    def test_sync_overwrites_keywords_and_weight(self):
        topic = self._edit_politics()
        call_command(
            'seed_news_sources', '--sync', stdout=StringIO(),
        )
        topic.refresh_from_db()
        seed = next(t for t in TOPICS if t['slug'] == 'politics')
        self.assertEqual(topic.keywords, seed['keywords'])
        self.assertEqual(topic.weight, seed['weight'])


class OrderedSourcesTests(TestCase):
    """news.preferences.ordered_sources — the reader's outlet
    ranking: preferred sources first by rank, the rest by
    importance_weight."""

    def setUp(self):
        self.a = _source('a', importance_weight=3.0)
        self.b = _source('b', importance_weight=2.0)
        self.c = _source('c', importance_weight=1.0)
        self.user = get_user_model().objects.create_user(
            username='reader', password='x',
        )

    def _slugs(self, user):
        return [s.slug for s in ordered_sources(user)]

    def test_anonymous_gets_weight_order(self):
        self.assertEqual(
            self._slugs(AnonymousUser()), ['a', 'b', 'c'],
        )

    def test_no_prefs_gets_weight_order(self):
        self.assertEqual(self._slugs(self.user), ['a', 'b', 'c'])

    def test_preferred_first_by_rank_then_weight_order(self):
        NewsSourcePreference.objects.create(
            user=self.user, source=self.c, rank=1,
        )
        NewsSourcePreference.objects.create(
            user=self.user, source=self.a, rank=2,
        )
        self.assertEqual(self._slugs(self.user), ['c', 'a', 'b'])

    def test_preferred_but_disabled_source_drops_out(self):
        self.c.is_enabled = False
        self.c.save()
        NewsSourcePreference.objects.create(
            user=self.user, source=self.c, rank=1,
        )
        self.assertEqual(self._slugs(self.user), ['a', 'b'])


class OrderedStoryArticlesTests(TestCase):
    """news.preferences.ordered_story_articles — which member
    article a story shows."""

    def setUp(self):
        self.a = _source('a', importance_weight=3.0)
        self.b = _source('b', importance_weight=1.0)
        self.user = get_user_model().objects.create_user(
            username='reader', password='x',
        )
        self.story = NewsStory.objects.create(
            title='Stāsts',
            published_date=timezone.localdate(),
        )
        self.art_a = _article(
            self.a, 'Stāsts A', story=self.story,
            story_match_status='auto',
        )
        self.art_b = _article(
            self.b, 'Stāsts B', story=self.story,
            story_match_status='auto',
        )

    def test_candidate_member_never_wins(self):
        self.art_a.story_match_status = 'candidate'
        self.art_a.save()
        # Even when 'a' is the top-ranked favorite, an
        # unreviewed candidate link is not published coverage.
        NewsSourcePreference.objects.create(
            user=self.user, source=self.a, rank=1,
        )
        self.assertEqual(
            ordered_story_articles(self.story, self.user),
            [self.art_b],
        )

    def test_favorite_covering_outlet_first(self):
        NewsSourcePreference.objects.create(
            user=self.user, source=self.b, rank=1,
        )
        self.assertEqual(
            ordered_story_articles(self.story, self.user),
            [self.art_b, self.art_a],
        )

    def test_anonymous_falls_back_to_weight_order(self):
        self.assertEqual(
            ordered_story_articles(self.story, AnonymousUser()),
            [self.art_a, self.art_b],
        )


class StoryCardApiTests(TestCase):
    """GET /api/news/stories/<pk>/ — the inline reader card as
    JSON (the retired /news/story/<pk>/fragment/ partial)."""

    def setUp(self):
        self.a = _source('a', importance_weight=3.0)
        self.b = _source('b', importance_weight=1.0)
        self.user = get_user_model().objects.create_user(
            username='reader', password='x',
        )
        self.story = NewsStory.objects.create(
            title='Stāsts',
            published_date=timezone.localdate(),
        )
        self.art_a = _article(
            self.a, 'Stāsts A', story=self.story,
            story_match_status='auto',
        )
        self.art_b = _article(
            self.b, 'Stāsts B', story=self.story,
            story_match_status='auto',
        )
        self.url = f'/api/news/stories/{self.story.pk}/'

    def _slugs(self, payload):
        return [
            ref['source_slug'] for ref in payload['other_articles']
        ]

    def test_renders_default_weight_pick(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['story_id'], self.story.pk)
        self.assertEqual(payload['article']['id'], self.art_a.pk)
        self.assertEqual(payload['article']['title'], 'Stāsts A')
        self.assertEqual(payload['article']['source_slug'], 'a')
        self.assertEqual(self._slugs(payload), ['b'])
        # No ready audio on disk — the card renders the
        # disabled Klausīties button off this field.
        self.assertIsNone(payload['audio_url'])

    def test_renders_preferred_article_when_logged_in(self):
        # auth=None still reads the session — logged-in
        # readers keep preference-ordered picks.
        NewsSourcePreference.objects.create(
            user=self.user, source=self.b, rank=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(
            response.json()['article']['id'], self.art_b.pk,
        )

    def test_source_override_picks_that_outlet(self):
        response = self.client.get(self.url, {'source': 'b'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['article']['id'], self.art_b.pk)
        self.assertEqual(self._slugs(payload), ['a'])

    def test_unknown_source_slug_falls_back(self):
        response = self.client.get(self.url, {'source': 'nope'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['article']['id'], self.art_a.pk,
        )

    def test_source_with_only_candidate_member_falls_back(self):
        # A 'candidate' link is not confirmed coverage, so the
        # slug matches no member article and the default pick
        # stands — same as an unknown slug.
        c = _source('c')
        _article(
            c, 'Stāsts C', story=self.story,
            story_match_status='candidate',
        )
        response = self.client.get(self.url, {'source': 'c'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['article']['id'], self.art_a.pk,
        )

    def test_no_confirmed_members_404s(self):
        NewsArticle.objects.filter(story=self.story).update(
            story_match_status='candidate',
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)


class PreferencesApiTests(TestCase):
    """GET|POST /api/news/preferences/ — the outlet ranking
    form behind django_auth (the retired /news/preferences/
    view). Presence in `rows` is the include checkbox."""

    def setUp(self):
        self.a = _source('a', importance_weight=3.0)
        self.b = _source('b', importance_weight=2.0)
        self.c = _source('c', importance_weight=1.0)
        self.user = get_user_model().objects.create_user(
            username='reader', password='x',
        )
        self.url = '/api/news/preferences/'

    def _prefs(self):
        return list(
            NewsSourcePreference.objects
            .filter(user=self.user)
            .order_by('rank')
            .values_list('source__slug', 'rank')
        )

    def test_anonymous_get_401s_with_login_url(self):
        """Anonymous GET answers the JSON 401 handshake — the
        login_url's `next` rewrites to the SPA page, the same
        bounce the old @login_required 302 performed."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)
        payload = response.json()
        self.assertEqual(payload['error'], 'unauthenticated')
        self.assertIn('/accounts/login/', payload['login_url'])
        self.assertIn(
            'next=%2Fnews%2Fpreferences%2F',
            payload['login_url'],
        )

    def test_anonymous_post_401s(self):
        response = self.client.post(
            self.url, {'rows': []},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)

    def test_get_prefills_existing_ranks(self):
        NewsSourcePreference.objects.create(
            user=self.user, source=self.b, rank=1,
        )
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        rows = {
            row['slug']: row
            for row in response.json()['rows']
        }
        # Enabled sources in the canonical
        # (-importance_weight, pk) order.
        self.assertEqual(list(rows), ['a', 'b', 'c'])
        self.assertTrue(rows['b']['checked'])
        self.assertEqual(rows['b']['rank'], 1)
        self.assertFalse(rows['a']['checked'])
        self.assertIsNone(rows['a']['rank'])

    def test_post_writes_rows_in_submitted_rank_order(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
            'rows': [
                {'slug': 'a', 'rank': 5},
                {'slug': 'b', 'rank': 1},
            ],
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['saved'], 2)
        # Submitted ranks (b=1, a=5) decide, not input order.
        self.assertEqual(self._prefs(), [('b', 1), ('a', 2)])

    def test_second_post_replaces_rows(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {
            'rows': [
                {'slug': 'a', 'rank': 1},
                {'slug': 'b', 'rank': 2},
            ],
        }, content_type='application/json')
        self.client.post(self.url, {
            'rows': [{'slug': 'c', 'rank': 1}],
        }, content_type='application/json')
        self.assertEqual(self._prefs(), [('c', 1)])

    def test_post_ignores_disabled_and_unknown_slugs(self):
        self.c.is_enabled = False
        self.c.save()
        self.client.force_login(self.user)
        self.client.post(self.url, {
            'rows': [
                {'slug': 'a', 'rank': 1},
                {'slug': 'c', 'rank': 2},
                {'slug': 'ghost', 'rank': 3},
            ],
        }, content_type='application/json')
        self.assertEqual(self._prefs(), [('a', 1)])

    def test_checked_but_unranked_sinks_below_numbered(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {
            'rows': [
                {'slug': 'a', 'rank': 3},
                {'slug': 'b', 'rank': None},
            ],
        }, content_type='application/json')
        self.assertEqual(self._prefs(), [('a', 1), ('b', 2)])


class NewsShellTests(TestCase):
    """The /news/ SPA shell contract — retired form-action and
    fragment URLs can't answer, client routes render."""

    def test_post_on_spa_path_404s(self):
        # The retired POST /news/preferences/ form action —
        # mutations live under /api/ now.
        response = self.client.post('/news/preferences/')
        self.assertEqual(response.status_code, 404)

    def test_retired_fragment_get_serves_shell(self):
        # GET /news/story/<pk>/fragment/ — falls into the
        # catch-all; React Router's '*' navigates to /news/.
        response = self.client.get('/news/story/1/fragment/')
        self.assertEqual(response.status_code, 200)

    def test_retired_audio_get_serves_shell(self):
        # 'audio' resolves through the <str:date>/ pattern —
        # a single-segment str — into the shell either way.
        response = self.client.get('/news/audio/')
        self.assertEqual(response.status_code, 200)

    def test_digest_detail_route_serves_page(self):
        # The day page is server-rendered — it needs a digest
        # row for the date, otherwise it's an honest 404.
        NewsDigest.objects.create(date=date(2026, 10, 29))
        response = self.client.get('/news/2026-10-29/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'spa-bootstrap', response.content)


class ArticleAudioViewTests(TestCase):
    """GET /news/article/<pk>/audio/ — the TTS seam endpoint."""

    def setUp(self):
        self.source = _source('a')
        self.article = _article(self.source, 'Ziņa')
        self.url = f'/news/article/{self.article.pk}/audio/'

    def test_404_without_audio_row(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_404_when_row_not_ready(self):
        NewsArticleAudio.objects.create(
            article=self.article, engine='test', text='t',
            text_sha256='x' * 64, status='pending',
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_404_when_ready_but_file_missing(self):
        NewsArticleAudio.objects.create(
            article=self.article, engine='test', text='t',
            text_sha256='x' * 64, status='ready',
            file_path='/nonexistent/audio.mp3',
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_200_serves_ready_audio_file(self):
        with tempfile.NamedTemporaryFile(
            suffix='.mp3', delete=False,
        ) as tmp:
            tmp.write(b'audio-bytes')
            path = tmp.name
        self.addCleanup(os.unlink, path)
        NewsArticleAudio.objects.create(
            article=self.article, engine='test', text='t',
            text_sha256='x' * 64, status='ready', file_path=path,
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b''.join(response.streaming_content), b'audio-bytes',
        )


@override_settings(GCS_AUDIO_BUCKET='test-bucket')
class TextToAudioTests(TestCase):
    """news.audio.text_to_audio — validation, sanitization,
    whitelist lang detection, dedup, upload and signing, all
    covered without touching GCS (every client is patched)."""

    @contextlib.contextmanager
    def _pipeline(self, blob_exists=False, creds=None):
        with (
            patch('news.audio.storage.Client') as client_cls,
            patch('news.audio.gTTS') as gtts,
            patch('news.audio.detect_langs') as detect,
            patch('news.audio.google.auth.default') as auth,
            patch('news.audio.Request'),
        ):
            bucket = client_cls.return_value.bucket.return_value
            blob = bucket.blob.return_value
            bucket.list_blobs.return_value = []
            blob.exists.return_value = blob_exists
            blob.generate_signed_url.return_value = (
                'https://signed.example/clip.mp3'
            )
            auth.return_value = (creds or Mock(), 'project')
            detect.return_value = [
                SimpleNamespace(lang='lv', prob=0.99),
            ]
            yield SimpleNamespace(
                client_cls=client_cls, gtts=gtts, detect=detect,
                auth=auth, blob=blob, bucket=bucket,
            )

    def test_invalid_text_never_reaches_pipeline(self):
        with self._pipeline() as m:
            for bad in ('', None, 42, 'x' * 5001):
                with self.assertRaises(ValueError):
                    text_to_audio(bad)
            m.client_cls.assert_not_called()

    def test_sanitizes_before_synthesis(self):
        with self._pipeline() as m:
            text_to_audio(
                'Skaties  https://a.lv/x--y  --==~~  lieliski'
            )
        spoken = m.gtts.call_args.kwargs['text']
        self.assertEqual(spoken.count('web link'), 1)
        self.assertNotRegex(spoken, r'[-_~=*]{2,}')
        self.assertNotIn('  ', spoken)

    def test_lang_argmax_within_whitelist(self):
        # 'de' wins globally but is not speakable — 'lv' must
        # beat 'en' inside the whitelist instead of detect()'s
        # global winner being used.
        with self._pipeline() as m:
            m.detect.return_value = [
                SimpleNamespace(lang='de', prob=0.99),
                SimpleNamespace(lang='lv', prob=0.7),
                SimpleNamespace(lang='en', prob=0.3),
            ]
            text_to_audio('Sveiki')
        self.assertEqual(m.gtts.call_args.kwargs['lang'], 'lv')

    def test_no_whitelist_hit_defaults_lv(self):
        with self._pipeline() as m:
            m.detect.return_value = [
                SimpleNamespace(lang='de', prob=0.99),
            ]
            text_to_audio('Sveiki')
        self.assertEqual(m.gtts.call_args.kwargs['lang'], 'lv')

    def test_detect_exception_defaults_lv(self):
        with self._pipeline() as m:
            m.detect.side_effect = LangDetectException(
                ErrorCode.CantDetectError, 'no features'
            )
            text_to_audio('Sveiki')
        self.assertEqual(m.gtts.call_args.kwargs['lang'], 'lv')

    def test_existing_blob_resigns_without_synthesis(self):
        with self._pipeline(blob_exists=True) as m:
            url = text_to_audio('Sveiki')
        m.gtts.assert_not_called()
        m.blob.upload_from_filename.assert_not_called()
        m.blob.generate_signed_url.assert_called_once()
        self.assertEqual(url, 'https://signed.example/clip.mp3')

    def test_fresh_clip_synthesizes_uploads_signs(self):
        def fake_save(path):
            with open(path, 'wb') as f:
                f.write(b'mp3')

        with self._pipeline() as m:
            m.gtts.return_value.save.side_effect = fake_save
            url = text_to_audio('Sveiki')
            path = m.gtts.return_value.save.call_args.args[0]
            # The temp file is unlinked in `finally` — nothing
            # may leak on disk after upload.
            self.assertFalse(os.path.exists(path))
        m.gtts.return_value.save.assert_called_once()
        upload = m.blob.upload_from_filename.call_args.kwargs
        self.assertEqual(upload['content_type'], 'audio/mpeg')
        sign = m.blob.generate_signed_url.call_args.kwargs
        self.assertEqual(sign['version'], 'v4')
        self.assertEqual(sign['expiration'], timedelta(days=7))
        self.assertEqual(sign['method'], 'GET')
        self.assertEqual(url, 'https://signed.example/clip.mp3')

    def test_metadata_creds_sign_via_iam_signblob(self):
        # Cloud Run metadata creds are not SA credentials —
        # signing must go through IAM signBlob.
        creds = Mock()
        creds.service_account_email = 'run@sa'
        creds.token = 'tok'
        with self._pipeline(creds=creds) as m:
            text_to_audio('Sveiki')
        sign = m.blob.generate_signed_url.call_args.kwargs
        self.assertEqual(sign['service_account_email'], 'run@sa')
        self.assertEqual(sign['access_token'], 'tok')

    def test_auth_requests_cloud_platform_scope(self):
        # The access token is also handed to the iamcredentials
        # signBlob API — devstorage.*-only scopes 403 there.
        with self._pipeline() as m:
            text_to_audio('Sveiki')
        scopes = m.auth.call_args.kwargs['scopes']
        self.assertEqual(
            scopes,
            ['https://www.googleapis.com/auth/cloud-platform'],
        )

    def test_sa_creds_sign_without_signblob_kwargs(self):
        creds = Mock(spec=service_account.Credentials)
        with self._pipeline(creds=creds) as m:
            text_to_audio('Sveiki')
        sign = m.blob.generate_signed_url.call_args.kwargs
        self.assertNotIn('service_account_email', sign)
        self.assertNotIn('access_token', sign)

    @override_settings(GCS_AUDIO_BUCKET='')
    def test_unset_bucket_raises_not_configured(self):
        with self._pipeline() as m:
            with self.assertRaises(AudioGenerationError) as ctx:
                text_to_audio('Sveiki')
            self.assertEqual(
                str(ctx.exception), 'GCS storage not configured'
            )
            m.client_cls.assert_not_called()

    def test_filename_prefixes_blob_name(self):
        with self._pipeline() as m:
            text_to_audio('Sveiki', filename='t-abc:def/ghi')
        blob_name = (
            m.client_cls.return_value
            .bucket.return_value
            .blob.call_args.args[0]
        )
        self.assertTrue(blob_name.startswith('audio/t-abc-def'))
        digest = hashlib.sha256(b'lv:Sveiki').hexdigest()[:16]
        self.assertEqual(
            blob_name, f'audio/t-abc-def-ghi-{digest}.mp3'
        )

    def _fake_blobs(self, count):
        base = datetime(2026, 1, 1, tzinfo=dtz.utc)
        return [
            SimpleNamespace(
                time_created=base + timedelta(days=i),
                delete=Mock(),
            )
            for i in range(count)
        ]

    def test_evicts_oldest_clip_at_cap(self):
        # A fresh upload on a full bucket deletes the oldest
        # clip so the count never exceeds the cap.
        with self._pipeline() as m:
            m.bucket.list_blobs.return_value = self._fake_blobs(
                500
            )
            text_to_audio('Sveiki')
            listed = m.bucket.list_blobs.return_value
        deleted = [b for b in listed if b.delete.called]
        self.assertEqual(len(deleted), 1)
        self.assertIs(deleted[0], listed[0])
        m.gtts.return_value.save.assert_called_once()

    def test_evicts_as_many_as_needed_over_cap(self):
        with self._pipeline() as m:
            m.bucket.list_blobs.return_value = self._fake_blobs(
                510
            )
            text_to_audio('Sveiki')
            listed = m.bucket.list_blobs.return_value
        deleted = [b for b in listed if b.delete.called]
        self.assertEqual(len(deleted), 11)
        self.assertEqual(deleted, listed[:11])

    def test_no_eviction_below_cap(self):
        with self._pipeline() as m:
            m.bucket.list_blobs.return_value = self._fake_blobs(3)
            text_to_audio('Sveiki')
            listed = m.bucket.list_blobs.return_value
        for b in listed:
            b.delete.assert_not_called()

    def test_dedup_never_lists_bucket(self):
        with self._pipeline(blob_exists=True) as m:
            text_to_audio('Sveiki')
        m.bucket.list_blobs.assert_not_called()

    def test_eviction_failure_still_returns_url(self):
        with self._pipeline() as m:
            m.bucket.list_blobs.side_effect = RuntimeError(
                'denied'
            )
            url = text_to_audio('Sveiki')
        self.assertEqual(url, 'https://signed.example/clip.mp3')

    def test_oversized_clip_rejected_before_upload(self):
        # A synthesized file over the 1 MB ceiling must never
        # reach the bucket — and the temp file is still cleaned.
        def fake_save(path):
            with open(path, 'wb') as f:
                f.write(b'0' * (1024 * 1024 + 1))

        with self._pipeline() as m:
            m.gtts.return_value.save.side_effect = fake_save
            with self.assertRaises(AudioGenerationError):
                text_to_audio('Sveiki')
            path = m.gtts.return_value.save.call_args.args[0]
            self.assertFalse(os.path.exists(path))
        m.blob.upload_from_filename.assert_not_called()


class AudioEndpointTests(TestCase):
    """GET /api/news/audio/ — the public JSON contract behind
    the digest page's audio buttons (the retired /news/audio/
    view). Schema bounds 422 the malformed cases the view
    400ed — uniform with the rest of the API."""

    def test_anonymous_get_returns_audio_url(self):
        with patch(
            'news.audio.text_to_audio',
            return_value='https://signed.example/clip.mp3',
        ):
            response = self.client.get(
                '/api/news/audio/', {'text': 'Sveiki'}
            )
        # 200 for an anonymous request — /news/ is public, so
        # the endpoint must not bounce to the login page.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {'audio_url': 'https://signed.example/clip.mp3'},
        )

    def test_missing_oversized_text_422_and_bad_lang_400(self):
        # Missing/oversized text is a schema bound — 422.
        self.assertEqual(
            self.client.get('/api/news/audio/').status_code, 422
        )
        self.assertEqual(
            self.client.get(
                '/api/news/audio/', {'text': 'x' * 6001}
            ).status_code,
            422,
        )
        # 'english' fails the manual _LANG_RE shape check —
        # still 400 like the view, not a 422.
        self.assertEqual(
            self.client.get(
                '/api/news/audio/',
                {'text': 'hi', 'lang': 'english'},
            ).status_code,
            400,
        )

    def test_oversized_filename_422_and_unsupported_lang_400(
        self,
    ):
        self.assertEqual(
            self.client.get(
                '/api/news/audio/',
                {'text': 'hi', 'filename': 'f' * 201},
            ).status_code,
            422,
        )
        # 'zz' passes the shape regex but is not a gTTS
        # voice — bad input (400), not a pipeline failure.
        self.assertEqual(
            self.client.get(
                '/api/news/audio/', {'text': 'hi', 'lang': 'zz'}
            ).status_code,
            400,
        )

    def test_pipeline_errors_map_to_400_and_502(self):
        with patch(
            'news.audio.text_to_audio',
            side_effect=ValueError('bad input'),
        ):
            response = self.client.get(
                '/api/news/audio/', {'text': 'x'}
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'bad_request')
        with patch(
            'news.audio.text_to_audio',
            side_effect=AudioGenerationError('down'),
        ):
            response = self.client.get(
                '/api/news/audio/', {'text': 'x'}
            )
        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertEqual(payload['error'], 'upstream_error')
        self.assertEqual(payload['detail'], 'down')

    def test_missing_media_deps_502_not_500(self):
        # The lazy news.audio import pulls optional media deps
        # (gTTS, langdetect, google-cloud-storage). A deployment
        # without them must degrade to "pipeline down" (502 —
        # the SPA's audio-unavailable signal), not an unhandled
        # 500. None in sys.modules makes the import raise
        # ImportError, like a bundle missing the deps.
        with patch.dict(sys.modules, {'news.audio': None}):
            response = self.client.get(
                '/api/news/audio/', {'text': 'x'}
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error'], 'upstream_error')

    def test_post_is_405(self):
        self.assertEqual(
            self.client.post(
                '/api/news/audio/', {'text': 'x'}
            ).status_code,
            405,
        )


class DigestListAudioPayloadTests(TestCase):
    """GET /api/news/digests/ carries each item's spoken text
    (headline + representative lead) — the audio buttons in
    the SPA synthesize from these fields (the DOM contract of
    the retired template moves to Vitest)."""

    def setUp(self):
        self.today = timezone.localdate()
        self.digest = NewsDigest.objects.create(date=self.today)
        for rank, (title, lead) in enumerate((
            ('Ziņa viens', 'Pirmais apraksts.'),
            ('Ziņa divi', 'Otrais apraksts.'),
        ), start=1):
            story = NewsStory.objects.create(
                title=title,
                published_date=self.today,
                representative_lead=lead,
            )
            NewsDigestItem.objects.create(
                digest=self.digest, story=story, rank=rank,
                headline=title,
            )

    def test_items_carry_spoken_text_fields(self):
        response = self.client.get('/api/news/digests/')
        self.assertEqual(response.status_code, 200)
        digests = response.json()['digests']
        self.assertEqual(len(digests), 1)
        items = digests[0]['items']
        self.assertEqual(
            [
                (i['story_id'], i['headline'],
                 i['representative_lead'])
                for i in items
            ],
            [
                (
                    item.story_id,
                    item.headline,
                    item.story.representative_lead,
                )
                for item in self.digest.items.order_by('rank')
            ],
        )


class DigestListApiTests(TestCase):
    """GET /api/news/digests/ — the ?date/?period filter
    contract: default is a 7-day window ending on the latest
    digest, period=day pins the anchor, period=all lists
    everything, and malformed params fall back to the default
    window (never 400/500 on a public page — `date` stays a
    str parsed by strptime inside the op so garbage never
    422s)."""

    def setUp(self):
        # Ten consecutive digest days: 2026-10-20 .. 2026-10-29.
        self.first = date(2026, 10, 20)
        for offset in range(10):
            NewsDigest.objects.create(
                date=self.first + timedelta(days=offset)
            )
        self.latest = self.first + timedelta(days=9)

    def _dates(self, response):
        return [d['date'] for d in response.json()['digests']]

    def _week_ending(self, anchor):
        return [
            (anchor - timedelta(days=i)).isoformat()
            for i in range(7)
        ]

    def test_defaults_to_week_ending_on_latest_digest(self):
        response = self.client.get('/api/news/digests/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._dates(response), self._week_ending(self.latest)
        )

    def test_day_period_filters_to_anchor(self):
        anchor = self.first + timedelta(days=3)
        response = self.client.get(
            '/api/news/digests/',
            {'date': anchor.isoformat(), 'period': 'day'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._dates(response), [anchor.isoformat()]
        )

    def test_day_period_without_date_shows_latest_day(self):
        # With no anchor, period=day pins the newest digest —
        # just that single day, not the week window.
        response = self.client.get(
            '/api/news/digests/', {'period': 'day'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._dates(response), [self.latest.isoformat()]
        )

    def test_week_period_inclusive_edges(self):
        anchor = self.first + timedelta(days=7)
        response = self.client.get(
            '/api/news/digests/',
            {'date': anchor.isoformat(), 'period': 'week'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._dates(response), self._week_ending(anchor)
        )

    def test_date_without_period_means_week(self):
        anchor = self.first + timedelta(days=7)
        response = self.client.get(
            '/api/news/digests/', {'date': anchor.isoformat()}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._dates(response), self._week_ending(anchor)
        )

    def test_period_all_lists_every_digest(self):
        for params in (
            {'period': 'all'},
            {'date': self.first.isoformat(), 'period': 'all'},
        ):
            response = self.client.get('/api/news/digests/', params)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(self._dates(response)), 10)
            self.assertEqual(
                self._dates(response)[0], self.latest.isoformat()
            )
            self.assertEqual(
                self._dates(response)[-1], self.first.isoformat()
            )

    def test_malformed_params_fall_back_to_default(self):
        for params in (
            {'date': 'garbage'},
            {'date': '2026-13-40'},
            # Over-length values must also fall back — the
            # params carry no max_length, so they reach the
            # strptime/membership guards instead of a 422.
            {'date': '2026-10-29xx'},
            {'period': 'bogus-but-over-ten-chars'},
            {'period': 'bogus'},
            {'date': 'garbage', 'period': 'bogus'},
        ):
            response = self.client.get('/api/news/digests/', params)
            self.assertEqual(response.status_code, 200, params)
            self.assertEqual(
                self._dates(response),
                self._week_ending(self.latest),
                params,
            )

    def test_anchor_on_empty_range_returns_empty_list(self):
        # A valid anchor over an empty window still 200s with
        # the filter state echoed — the SPA renders the
        # 'Šajā periodā nav neviena' empty state because
        # max_date is set.
        response = self.client.get(
            '/api/news/digests/',
            {'date': '2030-01-01', 'period': 'week'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['digests'], [])
        self.assertEqual(payload['max_date'], self.latest.isoformat())

    def test_empty_db_returns_null_bounds(self):
        NewsDigest.objects.all().delete()
        response = self.client.get('/api/news/digests/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['digests'], [])
        # Nothing to anchor on — the SPA hides the filter and
        # shows the global empty state off these nulls.
        self.assertIsNone(payload['min_date'])
        self.assertIsNone(payload['max_date'])
        self.assertIsNone(payload['anchor_date'])

    def test_filter_state_echoes(self):
        # The SPA renders the filter inputs and the range line
        # from the echoed effective state.
        response = self.client.get('/api/news/digests/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['period'], 'week')
        self.assertEqual(
            payload['anchor_date'], self.latest.isoformat()
        )
        self.assertEqual(
            payload['range_start'],
            (self.latest - timedelta(days=6)).isoformat(),
        )
        self.assertEqual(
            payload['range_end'], self.latest.isoformat()
        )
        self.assertEqual(
            payload['min_date'], self.first.isoformat()
        )
        self.assertEqual(
            payload['max_date'], self.latest.isoformat()
        )


BACKFILL_URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
<url>
  <loc>https://a.lv/raksts/zinas/29.10.2026-viena</loc>
  <lastmod>2026-10-30T08:00:00+02:00</lastmod>
  <news:news>
    <news:publication_date>2026-10-29T07:00:00+02:00
    </news:publication_date>
  </news:news>
</url>
<url>
  <loc>https://a.lv/raksts/zinas/28.10.2026-divi</loc>
  <lastmod>2026-10-29T08:00:00+02:00</lastmod>
</url>
</urlset>"""

BACKFILL_INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://ir.lv/sitemap/sitemap_pages.xml</loc>
</sitemap>
<sitemap><loc>https://ir.lv/sitemap/sitemap_articles_2026_44.xml
</loc></sitemap>
<sitemap><loc>https://ir.lv/sitemap/sitemap_articles_2015_07.xml
</loc></sitemap>
<sitemap><loc>https://ir.lv/sitemap/sitemap_articles_2009_01.xml
</loc></sitemap>
</sitemapindex>"""

BACKFILL_INDEX_REBALTICA = (
    b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://rebaltica.lv/wp-sitemap-posts-page-1.xml
</loc></sitemap>
<sitemap><loc>https://rebaltica.lv/wp-sitemap-posts-post-1.xml
</loc></sitemap>
</sitemapindex>"""
)

BACKFILL_ROBOTS = (
    b"User-agent: *\n"
    b"Sitemap: https://ir.lv/sitemap/sitemap_index.xml\n"
)

BACKFILL_ARTICLE = b"""<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "NewsArticle",
 "headline": "Raksta virsraksts", "description": "Raksta lead.",
 "datePublished": "2020-05-04T09:00:00+03:00",
 "image": "https://a.lv/img.jpg"}
</script>
<meta property="og:title" content="Cits virsraksts"/>
</head><body>article body</body></html>"""

BACKFILL_ARTICLE_NODATE = (
    b"<html><head><title>Bez datuma</title></head>"
    b"<body>x</body></html>"
)


def _backfill_request(url, **kwargs):
    """make_request stand-in for backfill tests — routes by URL
    shape: robots -> a per-host index pointer, sitemap index ->
    the host's index, *.xml -> the urlset, else an article
    page. rebaltica gets its own index shape so its
    SitemapIndexStrategy finds matching children."""
    if 'robots.txt' in url:
        host = urlparse(url).netloc
        return _response(
            f'User-agent: *\nSitemap: https://{host}'
            f'/sitemap_index.xml\n'.encode()
        )
    if 'sitemap_index' in url or 'wp-sitemap.xml' in url:
        if 'rebaltica' in url:
            return _response(BACKFILL_INDEX_REBALTICA)
        return _response(BACKFILL_INDEX)
    if url.endswith('.xml'):
        return _response(BACKFILL_URLSET)
    if 'nodate' in url:
        return _response(BACKFILL_ARTICLE_NODATE)
    return _response(BACKFILL_ARTICLE)


class SitemapParseTests(TestCase):
    """parse_sitemap_xml: urlset/index kinds, news:pubdate
    extraction, malformed tolerance."""

    def test_urlset_entries_with_news_pubdate(self):
        kind, entries = parse_sitemap_xml(BACKFILL_URLSET)
        self.assertEqual(kind, 'urlset')
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            entries[0]['loc'],
            'https://a.lv/raksts/zinas/29.10.2026-viena',
        )
        self.assertEqual(
            entries[0]['news_pubdate'], '2026-10-29T07:00:00+02:00'
        )
        self.assertEqual(entries[1]['news_pubdate'], '')
        self.assertEqual(
            entries[1]['lastmod'], '2026-10-29T08:00:00+02:00'
        )

    def test_index_children(self):
        kind, entries = parse_sitemap_xml(BACKFILL_INDEX)
        self.assertEqual(kind, 'index')
        locs = [e['loc'] for e in entries]
        self.assertIn(
            'https://ir.lv/sitemap/sitemap_articles_2015_07.xml',
            locs,
        )
        self.assertEqual(len(locs), 4)

    def test_malformed_and_empty(self):
        self.assertEqual(parse_sitemap_xml(b'<broken'), (None, []))
        self.assertEqual(parse_sitemap_xml(b''), (None, []))
        self.assertEqual(parse_sitemap_xml(None), (None, []))


class PartitionEnumerationTests(TestCase):
    """Strategy partition arithmetic: bounds, newest-first
    order, URL shapes, index filtering."""

    def setUp(self):
        self.source = SimpleNamespace(name='X', slug='x')

    def test_week_strategy_bounds_and_order(self):
        strategy = WeekSitemapStrategy(
            'https://x.lv/{year}W{week:02d}.xml',
            earliest=date(2023, 11, 1),
        )
        parts = strategy.enumerate_partitions(
            None, self.source, date(2026, 1, 11)
        )
        # Jan 5-11 2026 is ISO week 2; Nov 1 2023's week is
        # 2023-W44 (its Monday is Oct 30).
        self.assertEqual(parts[0].key, '2026-W02')
        self.assertEqual(
            parts[0].url, 'https://x.lv/2026W02.xml'
        )
        self.assertEqual(parts[-1].key, '2023-W44')
        keys = [p.key for p in parts]
        self.assertEqual(keys, sorted(keys, reverse=True))
        self.assertEqual(
            parts[0].start, date(2026, 1, 5)
        )
        self.assertEqual(parts[0].end, date(2026, 1, 11))

    def test_month_strategy_bounds_and_order(self):
        strategy = MonthSitemapStrategy(
            'https://x.lv/{year}-{month:02d}/index.xml',
            earliest=date(2013, 6, 1),
        )
        parts = strategy.enumerate_partitions(
            None, self.source, date(2013, 8, 20)
        )
        self.assertEqual(
            [p.key for p in parts],
            ['2013-08', '2013-07', '2013-06'],
        )
        self.assertEqual(
            parts[0].url, 'https://x.lv/2013-08/index.xml'
        )
        self.assertEqual(parts[-1].end, date(2013, 6, 30))

    def test_jauns_url_uses_month_first_day(self):
        part = BACKFILL_STRATEGIES['jauns'].enumerate_partitions(
            None, self.source, date(2026, 3, 15)
        )[0]
        self.assertEqual(part.key, '2026-03')
        self.assertEqual(
            part.url,
            'https://jauns.lv/sitemap/20260301/'
            'articles/2026_03.xml',
        )

    def test_chunk_probe_range_descending(self):
        strategy = ChunkProbeSitemapStrategy(
            'https://x.lv/sitemap-{n}.xml', range(1, 4)
        )
        parts = strategy.enumerate_partitions(
            None, self.source, date(2026, 1, 1)
        )
        self.assertEqual(
            [p.key for p in parts],
            ['sitemap-3', 'sitemap-2', 'sitemap-1'],
        )
        # Chunks carry no date bounds — --since/--until can
        # never filter them.
        self.assertIsNone(parts[0].start)

    def test_lvportals_month_partitions_and_url(self):
        strategy = BACKFILL_STRATEGIES['lvportals']
        parts = strategy.enumerate_partitions(
            None, self.source, date(2008, 3, 20)
        )
        self.assertEqual(
            [p.key for p in parts],
            ['2008-03', '2008-02', '2008-01'],
        )
        url = parts[0].url
        self.assertIn('lapa:1', url)
        self.assertIn('no:01.03.2008', url)
        self.assertIn('lidz:31.03.2008', url)

    def test_index_strategy_filters_children_by_year(self):
        scraper = SimpleNamespace(
            make_request=Mock(
                side_effect=[
                    _response(BACKFILL_ROBOTS),
                    _response(BACKFILL_INDEX),
                ]
            )
        )
        strategy = BACKFILL_STRATEGIES['ir']
        parts = strategy.enumerate_partitions(
            scraper, self.source, date(2026, 10, 30)
        )
        # sitemap_pages does not match the article regex;
        # 2009_01 is below earliest.year (2010).
        self.assertEqual(
            [p.key for p in parts], ['2026-44', '2015-07']
        )
        self.assertEqual(
            parts[1].url,
            'https://ir.lv/sitemap/sitemap_articles_2015_07.xml',
        )
        self.assertEqual(parts[0].start, date(2026, 1, 1))

    def test_lvportals_page_walk_stops_on_repeat(self):
        page1 = (
            b'<a href="/dienaskartiba/12345-zina-viena-2020">x</a>'
            b'<a href="/autors/12-autors">y</a>'
        )
        page2 = (
            b'<a href="/dienaskartiba/12345-zina-viena-2020">x</a>'
        )
        scraper = SimpleNamespace(
            make_request=Mock(
                side_effect=[_response(page1), _response(page2)]
            )
        )
        strategy = ArchiveMonthStrategy(earliest=date(2008, 1, 1))
        partition = Partition(
            key='2020-01', label='l', url='u',
            meta={'first': date(2020, 1, 1),
                  'last': date(2020, 1, 31)},
        )
        entries = strategy.iter_article_urls(scraper, partition)
        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0]['link'],
            'https://lvportals.lv/dienaskartiba/'
            '12345-zina-viena-2020',
        )

    def test_index_strategy_no_children_raises(self):
        """Discovery yielding zero matching children (dead
        index, non-XML error page) raises — the run must end
        FAILED, not deactivate the source's items via an
        empty synced set."""
        scraper = SimpleNamespace(
            make_request=Mock(
                side_effect=[
                    _response(b'User-agent: *\n'),
                    _response(b'<html>503</html>'),
                ]
            )
        )
        strategy = BACKFILL_STRATEGIES['ir']
        with self.assertRaises(RuntimeError):
            strategy.enumerate_partitions(
                scraper, self.source, date(2026, 10, 30)
            )

    def test_sitemap_listing_dead_fetch_raises(self):
        """make_request returning None (retries exhausted —
        429/5xx or a connection failure) is a transient
        outage, not an empty listing: iter_article_urls
        raises so the partition item fails and retries next
        run instead of burning to DONE."""
        scraper = SimpleNamespace(
            make_request=Mock(return_value=None)
        )
        strategy = BACKFILL_STRATEGIES['lsm']
        partition = Partition(key='k', label='l', url='u')
        with self.assertRaises(RuntimeError):
            strategy.iter_article_urls(scraper, partition)

    def test_lvportals_dead_first_page_raises(self):
        """A dead fetch on the FIRST archive page raises —
        'no links found' (a real but empty page) would return
        [] and end the walk, but None means the fetch died."""
        scraper = SimpleNamespace(
            make_request=Mock(return_value=None)
        )
        strategy = ArchiveMonthStrategy(earliest=date(2008, 1, 1))
        partition = Partition(
            key='2020-01', label='l', url='u',
            meta={'first': date(2020, 1, 1),
                  'last': date(2020, 1, 31)},
        )
        with self.assertRaises(RuntimeError):
            strategy.iter_article_urls(scraper, partition)

    def test_lvportals_dead_midwalk_page_raises(self):
        """A None response mid-walk (page 2 of N) fails the
        partition rather than completing on a truncated
        listing."""
        page1 = (
            b'<a href="/dienaskartiba/12345-zina-viena-2020">'
            b'x</a>'
        )
        scraper = SimpleNamespace(
            make_request=Mock(
                side_effect=[_response(page1), None]
            )
        )
        strategy = ArchiveMonthStrategy(earliest=date(2008, 1, 1))
        partition = Partition(
            key='2020-01', label='l', url='u',
            meta={'first': date(2020, 1, 1),
                  'last': date(2020, 1, 31)},
        )
        with self.assertRaises(RuntimeError):
            strategy.iter_article_urls(scraper, partition)

    def test_lvportals_walk_stops_on_deadline(self):
        """A --max-minutes deadline cuts the page-walk and
        flags budget_exhausted so the month partition stays
        pending instead of being marked DONE on a partial
        listing."""
        page1 = (
            b'<a href="/dienaskartiba/12345-zina-viena-2020">'
            b'x</a>'
        )
        requested = []
        scraper = SimpleNamespace(budget_exhausted=False)
        scraper.make_request = Mock(
            side_effect=lambda url, **kw: (
                requested.append(url) or _response(page1)
            )
        )
        scraper._deadline_passed = lambda: len(requested) >= 1
        strategy = ArchiveMonthStrategy(earliest=date(2008, 1, 1))
        partition = Partition(
            key='2020-01', label='l', url='u',
            meta={'first': date(2020, 1, 1),
                  'last': date(2020, 1, 31)},
        )
        entries = strategy.iter_article_urls(scraper, partition)
        # Page 1 walked; the deadline stopped the page-2 fetch
        # (the same URL set would otherwise repeat-stop with
        # one extra request and no flag set).
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(requested), 1)
        self.assertTrue(scraper.budget_exhausted)


class MetadataExtractionTests(TestCase):
    """extract_article_metadata: JSON-LD (object + @graph),
    og:/meta fallbacks, URL-date regex, undateable -> None."""

    def test_jsonld_single_object(self):
        meta = extract_article_metadata(
            BACKFILL_ARTICLE, 'https://a.lv/x', 'a'
        )
        self.assertEqual(meta['title'], 'Raksta virsraksts')
        self.assertEqual(meta['lead'], 'Raksta lead.')
        self.assertEqual(meta['image_url'], 'https://a.lv/img.jpg')
        self.assertEqual(meta['published_at'].year, 2020)
        self.assertEqual(meta['published_at'].month, 5)

    def test_jsonld_graph(self):
        html = b"""<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
 {"@type": "WebPage", "name": "nav"},
 {"@type": "NewsArticle", "headline": "Graph title",
  "datePublished": "2019-02-03T10:00:00+02:00"}]}
</script></head><body/></html>"""
        meta = extract_article_metadata(html, 'https://a.lv/g', 'a')
        self.assertEqual(meta['title'], 'Graph title')
        self.assertEqual(meta['published_at'].year, 2019)

    def test_og_and_published_time_fallbacks(self):
        html = b"""<html><head>
<meta property="og:title" content="Og virsraksts"/>
<meta name="description" content="Meta apraksts"/>
<meta property="article:published_time"
      content="2018-11-12T08:30:00+02:00"/>
</head><body/></html>"""
        meta = extract_article_metadata(html, 'https://a.lv/o', 'a')
        self.assertEqual(meta['title'], 'Og virsraksts')
        self.assertEqual(meta['lead'], 'Meta apraksts')
        self.assertEqual(meta['published_at'].month, 11)

    def test_lsm_url_date_regex(self):
        meta = extract_article_metadata(
            BACKFILL_ARTICLE_NODATE,
            'https://www.lsm.lv/raksts/x/29.10.2026-foo.a297908/',
            'lsm',
        )
        self.assertEqual(meta['published_at'].day, 29)
        self.assertEqual(meta['published_at'].month, 10)
        self.assertEqual(meta['published_at'].year, 2026)

    def test_no_date_anywhere_is_none(self):
        meta = extract_article_metadata(
            BACKFILL_ARTICLE_NODATE, 'https://a.lv/nodate', 'a'
        )
        self.assertIsNone(meta['published_at'])

    def test_url_category_strategy(self):
        meta = extract_article_metadata(
            BACKFILL_ARTICLE_NODATE,
            'https://a.lv/raksts/zinas/latvija/x',
            'a',
            category_strategy='url',
        )
        self.assertEqual(
            meta['feed_categories'], ['zinas', 'latvija']
        )

    def test_normalize_link(self):
        self.assertEqual(
            normalize_link(
                'HTTPS://A.LV/x/?utm_source=fb&y=1#frag'
            ),
            'https://a.lv/x?y=1',
        )


class BackfillDedupTests(TestCase):
    """Two-key dedup: hash external_id + raw/normalized link."""

    def setUp(self):
        self.source = _source('lsm', 'url')
        self.scraper = NewsBackfillScraper()
        self.scraper._active_source = self.source
        self.scraper._active_partition = Partition(
            key='k', label='l', url='u'
        )

    def _result(self, link):
        return {
            'external_id': hashlib.sha256(
                link.encode()
            ).hexdigest()[:32],
            'link': link,
            'news_pubdate': None,
        }

    def test_guid_row_matched_by_link_not_rewritten(self):
        article = NewsArticle.objects.create(
            source=self.source,
            external_id='rss-guid-1',
            link='https://a.lv/x',
            title='Vecais',
            published_at=timezone.now(),
        )
        old_seen = article.last_seen
        with patch.object(
            NewsBackfillScraper, 'make_request'
        ) as mock_request:
            remaining = self.scraper.initiate_resources(
                [self._result('https://a.lv/x')]
            )
        self.assertEqual(remaining, [])
        mock_request.assert_not_called()
        article.refresh_from_db()
        self.assertEqual(article.external_id, 'rss-guid-1')
        self.assertGreater(article.last_seen, old_seen)

    def test_normalized_link_match(self):
        NewsArticle.objects.create(
            source=self.source,
            external_id='rss-guid-2',
            link='https://a.lv/y',
            title='T',
            published_at=timezone.now(),
        )
        with patch.object(
            NewsBackfillScraper, 'make_request'
        ) as mock_request:
            remaining = self.scraper.initiate_resources(
                [self._result('https://a.lv/y?utm_source=feed')]
            )
        # The sitemap-side tracking param is stripped by
        # normalize_link, so the stored plain link matches.
        self.assertEqual(remaining, [])
        mock_request.assert_not_called()

    def test_new_row_gets_hash_id_and_backfill_flag(self):
        link = 'https://a.lv/raksts/zinas/29.10.2026-viena'
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_backfill_request,
        ):
            articles = self.scraper.initiate_resources(
                [self._result(link)]
            )
        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertTrue(article.is_backfill)
        self.assertEqual(
            article.external_id,
            hashlib.sha256(link.encode()).hexdigest()[:32],
        )
        self.assertEqual(article.published_at.year, 2020)
        self.scraper.create_or_update_resources(articles)
        self.assertTrue(
            NewsArticle.objects.filter(
                external_id=article.external_id
            ).exists()
        )

    def test_undateable_article_is_skipped(self):
        """The clustering-protection rule: a row without
        published_at is never created."""
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_backfill_request,
        ):
            articles = self.scraper.initiate_resources(
                [self._result('https://a.lv/nodate-item')]
            )
        self.assertEqual(articles, [])
        self.assertEqual(NewsArticle.objects.count(), 0)

    def test_fetch_exception_skips_url_not_partition(self):
        """A malformed <loc> raising inside make_request is
        logged and skipped — the partition still completes."""
        def _boom(url, **kwargs):
            if 'broken' in url:
                raise ValueError('bad URL')
            return _backfill_request(url)

        results = [
            self._result('https://a.lv/broken-loc'),
            self._result(
                'https://a.lv/raksts/zinas/29.10.2026-viena'
            ),
        ]
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_boom,
        ):
            articles = self.scraper.initiate_resources(results)
        self.assertEqual(len(articles), 1)
        self.assertEqual(
            articles[0].link,
            'https://a.lv/raksts/zinas/29.10.2026-viena',
        )

    def test_known_row_update_reuses_match_queryset(self):
        """One SELECT for the match set, one UPDATE by pk —
        the OR'd ids+links filter must not be issued twice."""
        NewsArticle.objects.create(
            source=self.source,
            external_id='rss-guid-q',
            link='https://a.lv/x',
            title='T',
            published_at=timezone.now(),
        )
        with self.assertNumQueries(2):
            remaining = self.scraper._dedup_slice(
                self.source, [self._result('https://a.lv/x')]
            )
        self.assertEqual(remaining, [])

    def test_diena_arhivs_listing_urls_are_skipped(self):
        """sitemap-13's /arhivs/ day-listing locs never reach
        a fetch — day-page coverage is a planned follow-up."""
        urlset = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.diena.lv/arhivs/diena/05.01.2020</loc>
</url>
<url><loc>https://www.diena.lv/raksts/2020/01/05/raksts</loc>
</url>
</urlset>"""
        requested = []

        def _track(url, **kwargs):
            requested.append(url)
            if url.endswith('sitemap-13.xml'):
                return _response(urlset)
            return _response(BACKFILL_ARTICLE)

        self.scraper._active_source = _source('diena', 'url')
        self.scraper._active_strategy = BACKFILL_STRATEGIES[
            'diena'
        ]
        self.scraper._active_partition = Partition(
            key='sitemap-13', label='l',
            url='https://www.diena.lv/sitemap-13.xml',
        )
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_track,
        ):
            articles = self.scraper.scrape_portal(
                'https://www.diena.lv/sitemap-13.xml'
            )
        self.assertEqual(len(articles), 1)
        self.assertFalse(
            any('/arhivs/' in url for url in requested)
        )


class BackfillRunnerTests(TestCase):
    """Item keys, DONE-resume, --since pending/active
    invariants, failure isolation, budget stop."""

    def setUp(self):
        self.source = _source('lsm', 'url')
        self.runner = ScrapeJobRunner(
            slug='news.backfill', cycle_key='backfill'
        )
        # W02 (Jan 5-11 2026) is the only partition inside the
        # since/until window; W01 ends Jan 4.
        self.scraper = NewsBackfillScraper(
            runner=self.runner,
            since=date(2026, 1, 5),
            until=date(2026, 1, 11),
        )

    def test_item_keys_are_source_partition(self):
        keys = list(self.scraper.get_search_urls())
        self.assertEqual(
            keys,
            [
                'https://www.lsm.lv/assets/sitemap/'
                'news_lv_2026W02.xml'
            ],
        )
        item_keys = set(
            ScrapeJobItem.objects.values_list('key', flat=True)
        )
        self.assertIn('lsm:2026-W02', item_keys)
        self.assertTrue(
            all(k.startswith('lsm:') for k in item_keys)
        )

    def test_done_partition_skipped_on_rerun(self):
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_backfill_request,
        ):
            self.scraper.run()
        self.assertEqual(NewsArticle.objects.count(), 2)
        self.assertTrue(
            ScrapeJobRunItem.objects.filter(
                item__key='lsm:2026-W02',
                status=ScrapeJobRunItem.DONE,
            ).exists()
        )
        runner2 = ScrapeJobRunner(
            slug='news.backfill', cycle_key='backfill'
        )
        scraper2 = NewsBackfillScraper(
            runner=runner2,
            since=date(2026, 1, 5),
            until=date(2026, 1, 11),
        )
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_backfill_request,
        ):
            scraper2.run()
        self.assertEqual(NewsArticle.objects.count(), 2)
        self.assertFalse(
            ScrapeJobRunItem.objects.filter(
                run=runner2.run
            ).exists()
        )

    def test_since_leaves_out_of_range_pending_and_active(self):
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_backfill_request,
        ):
            self.scraper.run()
        item = ScrapeJobItem.objects.get(key='lsm:2026-W01')
        self.assertTrue(item.is_active)
        self.assertFalse(
            ScrapeJobRunItem.objects.filter(item=item).exists()
        )

    def test_until_before_earliest_deactivates_nothing(self):
        """Regression: --until narrows processing, never the
        synced item set — a run ending before the source's
        floor processes nothing but must leave every item
        active for a later wider run (is_active is
        admin-owned; sync never re-enables)."""
        scraper = NewsBackfillScraper(
            runner=self.runner,
            until=date(2020, 1, 1),
        )
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_backfill_request,
        ):
            scraper.run()
        self.assertTrue(ScrapeJobItem.objects.exists())
        self.assertFalse(
            ScrapeJobItem.objects.filter(is_active=False)
            .exists()
        )
        self.assertFalse(ScrapeJobRunItem.objects.exists())
        # A wider rerun re-syncs the same full range and
        # processes the in-window partition normally.
        runner2 = ScrapeJobRunner(
            slug='news.backfill', cycle_key='backfill'
        )
        scraper2 = NewsBackfillScraper(
            runner=runner2,
            since=date(2026, 1, 5),
            until=date(2026, 1, 11),
        )
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_backfill_request,
        ):
            scraper2.run()
        self.assertFalse(
            ScrapeJobItem.objects.filter(is_active=False)
            .exists()
        )
        self.assertTrue(
            ScrapeJobRunItem.objects.filter(
                item__key='lsm:2026-W02',
                status=ScrapeJobRunItem.DONE,
            ).exists()
        )

    def test_dead_listing_fetch_records_failed_not_done(self):
        """make_request returning None (retries exhausted on
        the partition's listing) records the item FAILED —
        the partition retries next run instead of being
        marked DONE on an outage."""

        def _dead_listing(url, **kwargs):
            if url.endswith('.xml'):
                return None
            return _backfill_request(url)

        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_dead_listing,
        ):
            self.scraper.run()
        statuses = {
            ri.item.key: ri.status
            for ri in ScrapeJobRunItem.objects.all()
        }
        self.assertEqual(
            statuses.get('lsm:2026-W02'), ScrapeJobRunItem.FAILED
        )

    def test_failed_partition_records_failed_continues(self):
        scraper = NewsBackfillScraper(
            runner=self.runner,
            since=date(2025, 12, 29),
            until=date(2026, 1, 11),
        )

        def _fail_w02(url, **kwargs):
            if 'W02' in url:
                raise ConnectionError('boom')
            return _backfill_request(url)

        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_fail_w02,
        ):
            scraper.run()
        statuses = {
            ri.item.key: ri.status
            for ri in ScrapeJobRunItem.objects.all()
        }
        # Newest-first order: W02 fails, W01 still completes.
        self.assertEqual(
            statuses.get('lsm:2026-W02'), ScrapeJobRunItem.FAILED
        )
        self.assertEqual(
            statuses.get('lsm:2026-W01'), ScrapeJobRunItem.DONE
        )

    def test_budget_exhausted_partition_not_done(self):
        def _stop(results):
            self.scraper.budget_exhausted = True
            return []

        self.scraper.initiate_resources = _stop
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_backfill_request,
        ):
            self.scraper.run()
        self.assertFalse(
            ScrapeJobRunItem.objects.filter(
                status=ScrapeJobRunItem.DONE
            ).exists()
        )


class BackfillCommandTests(TestCase):
    """scrape_news --backfill: dry-run listing, date
    validation, tvnet skip, budget -> PARTIAL."""

    def test_dry_run_lists_partitions_and_writes_nothing(self):
        out = StringIO()
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_backfill_request,
        ):
            call_command(
                'scrape_news',
                backfill=True,
                source='lsm',
                since='2026-10-26',
                until='2026-10-30',
                dry_run=True,
                stdout=out,
            )
        self.assertIn('[dry-run] lsm: 2026-W44 2', out.getvalue())
        self.assertEqual(NewsArticle.objects.count(), 0)
        self.assertEqual(ScrapeJobRun.objects.count(), 0)

    def test_bad_since_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                'scrape_news', backfill=True, since='not-a-date'
            )

    def test_since_after_until_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                'scrape_news',
                backfill=True,
                since='2026-10-30',
                until='2026-10-01',
            )

    def test_backfill_only_flags_without_backfill_raise(self):
        """--since/--until/--max-minutes on a plain feed run
        would be silently ignored — raise instead of hiding
        a mistyped invocation."""
        for kwargs in (
            {'since': '2026-01-01'},
            {'until': '2026-01-01'},
            {'max_minutes': 5},
        ):
            with self.assertRaises(CommandError):
                call_command('scrape_news', **kwargs)

    def test_tvnet_skip_and_partial(self):
        with (
            self.assertLogs('news', level='INFO') as logs,
            patch.object(
                NewsBackfillScraper,
                'make_request',
                side_effect=_backfill_request,
            ),
        ):
            call_command(
                'scrape_news',
                backfill=True,
                source='tvnet',
                stdout=StringIO(),
            )
        self.assertTrue(
            any('no historical listing' in m for m in logs.output)
        )
        run = ScrapeJobRun.objects.latest('id')
        self.assertEqual(run.status, ScrapeJobRun.PARTIAL)
        self.assertFalse(
            ScrapeJobRunItem.objects.filter(run=run).exists()
        )

    def test_dead_sitemap_index_fails_run_not_items(self):
        """A source whose sitemap index yields no children no
        longer fails the run before sync_items: its existing
        items sync as obj=None placeholders — kept active and
        pending (never done/failed), never deactivated —
        while healthy sources' items are still processed.
        The run itself still ends FAILED."""
        job = ensure_job('news.backfill')
        item = ScrapeJobItem.objects.create(
            job=job, key='ir:2020-01', label='ir 2020-01'
        )

        def _dead_index(url, **kwargs):
            if 'robots.txt' in url:
                return _response(b'User-agent: *\n')
            if 'sitemap' in url:
                return _response(b'<html>503</html>', status=503)
            return _backfill_request(url)

        with (
            patch.object(
                NewsBackfillScraper,
                'make_request',
                side_effect=_dead_index,
            ),
            self.assertRaises(CommandError),
        ):
            call_command(
                'scrape_news',
                backfill=True,
                source='lsm',
                stdout=StringIO(),
            )
        run = ScrapeJobRun.objects.latest('id')
        self.assertEqual(run.status, ScrapeJobRun.FAILED)
        item.refresh_from_db()
        self.assertTrue(item.is_active)
        # Pending — the placeholder was skipped at processing
        # time, never recorded done or failed.
        self.assertFalse(
            ScrapeJobRunItem.objects.filter(item=item).exists()
        )
        # Healthy sources still did their work — lsm's items
        # were synced and processed before the run failed.
        self.assertTrue(
            ScrapeJobRunItem.objects.filter(
                item__key__startswith='lsm:',
                status=ScrapeJobRunItem.DONE,
            ).exists()
        )

    def test_zero_budget_ends_partial(self):
        with patch.object(
            NewsBackfillScraper,
            'make_request',
            side_effect=_backfill_request,
        ):
            call_command(
                'scrape_news',
                backfill=True,
                source='lsm',
                max_minutes=0,
                stdout=StringIO(),
            )
        run = ScrapeJobRun.objects.get(
            job__slug='news.backfill'
        )
        self.assertEqual(run.status, ScrapeJobRun.PARTIAL)
        self.assertFalse(
            ScrapeJobRunItem.objects.filter(
                status=ScrapeJobRunItem.DONE
            ).exists()
        )


class RobotSurfaceTests(TestCase):
    """Crawler surface: /news/rss.xml, /sitemap.xml and /llms.txt
    must expose the digest with its URLs — the /news/ SPA shell
    serves a robot that can't run JavaScript no content at all."""

    def setUp(self):
        self.source = _source('a')
        self.topic = NewsTopic.objects.create(
            slug='politics', name='Politika', weight=1.0,
            keywords=['Saeima'],
        )
        self.today = timezone.localdate()

    def _digest(self, day, headline='Ziņa viens'):
        """A digest row with one ranked item whose story has one
        confirmed member article — the minimum a robot-facing
        surface needs to render a headline + URL."""
        story = NewsStory.objects.create(
            title=headline, topic=self.topic,
            published_date=day, importance_score=1.0,
            source_count=1,
        )
        article = _article(
            self.source, headline, topic=self.topic,
            story=story, story_match_status='auto',
        )
        digest = NewsDigest.objects.create(date=day)
        NewsDigestItem.objects.create(
            digest=digest, story=story, rank=1,
            headline=headline, rationale='1 outlet: a',
        )
        return article

    def test_rss_feed_lists_recent_digest_with_article_urls(self):
        article = self._digest(self.today)
        response = self.client.get('/news/rss.xml')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/rss+xml', response['Content-Type'])
        body = response.content.decode()
        self.assertIn('Ziņa viens', body)
        # Both URL kinds a robot needs: the digest-day page and
        # the member article link.
        self.assertIn(f'/news/{self.today.isoformat()}/', body)
        self.assertIn(article.link, body)

    def test_rss_feed_window_is_last_7_days(self):
        article = self._digest(
            self.today - timedelta(days=10), headline='Ziņa vecā'
        )
        self._digest(self.today)
        body = self.client.get('/news/rss.xml').content.decode()
        self.assertIn('Ziņa viens', body)
        self.assertNotIn('Ziņa vecā', body)
        self.assertNotIn(article.link, body)

    def test_rss_feed_empty_when_no_digests(self):
        response = self.client.get('/news/rss.xml')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'<item>', response.content)

    def test_news_shell_emits_rss_autodiscovery_link(self):
        response = self.client.get('/news/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'rel="alternate"', response.content)
        self.assertIn(b'/news/rss.xml', response.content)

    def test_sitemap_indexes_every_digest_day(self):
        old = self.today - timedelta(days=30)
        self._digest(old, headline='Ziņa vecā')
        self._digest(self.today)
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/xml', response['Content-Type'])
        body = response.content.decode()
        # The sitemap is an exhaustive inventory — even the
        # month-old digest day is listed with a lastmod.
        self.assertIn(f'/news/{old.isoformat()}/', body)
        self.assertIn(f'/news/{self.today.isoformat()}/', body)
        self.assertIn('<lastmod>', body)
        self.assertIn('/news/', body)

    def test_llms_lists_recent_digests_with_urls(self):
        article = self._digest(self.today)
        response = self.client.get('/llms.txt')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/plain', response['Content-Type'])
        body = response.content.decode()
        self.assertIn(f'/news/{self.today.isoformat()}/', body)
        self.assertIn('Ziņa viens', body)
        self.assertIn(article.link, body)
        self.assertIn('/news/rss.xml', body)

    def test_llms_window_is_last_7_days(self):
        self._digest(
            self.today - timedelta(days=10), headline='Ziņa vecā'
        )
        self._digest(self.today)
        body = self.client.get('/llms.txt').content.decode()
        self.assertIn('Ziņa viens', body)
        self.assertNotIn('Ziņa vecā', body)

    def test_digest_day_page_is_server_rendered(self):
        """/news/<date>/ ships the digest inside #root — a robot
        reads the HTML while React replaces it on mount."""
        article = self._digest(self.today)
        response = self.client.get(
            f'/news/{self.today.isoformat()}/'
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Ziņa viens', body)
        self.assertIn(article.link, body)
        # The SPA bootstrap still ships — React takes over #root.
        self.assertIn('spa-bootstrap', body)
        self.assertIn('news-ssr', body)

    def test_index_page_renders_last_7_days(self):
        self._digest(
            self.today - timedelta(days=10), headline='Ziņa vecā'
        )
        self._digest(self.today)
        body = self.client.get('/news/').content.decode()
        self.assertIn('Ziņa viens', body)
        self.assertNotIn('Ziņa vecā', body)

    def test_old_digest_day_stays_readable(self):
        """History beyond the 7-day window keeps a live page —
        the sitemap's full archive resolves to real HTML."""
        old = self.today - timedelta(days=30)
        self._digest(old, headline='Ziņa vecā')
        response = self.client.get(f'/news/{old.isoformat()}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Ziņa vecā', response.content.decode())

    def test_digest_page_date_contract(self):
        # A non-date segment is not our page — the plain shell
        # hands it to React Router (retired client routes).
        self.assertEqual(
            self.client.get('/news/not-a-date/').status_code, 200
        )
        # A parseable date IS a digest page: no row, honest 404 —
        # otherwise every YYYY-MM-DD is a soft-404 shell.
        missing = self.today - timedelta(days=3)
        self.assertEqual(
            self.client.get(
                f'/news/{missing.isoformat()}/'
            ).status_code,
            404,
        )


class NewsPipelineCommandTests(TestCase):
    """news_pipeline: the four daily phases checkpointed as
    ScrapeJobItems under job slug 'news.pipeline'. call_command
    is mocked out — what is under test is phase order,
    same-cycle resume, failure abort, --from and --dry-run."""

    MODULE = 'news.management.commands.news_pipeline'

    def _run(self, **kwargs):
        out = StringIO()
        with patch(f'{self.MODULE}.call_command') as cc:
            call_command('news_pipeline', stdout=out, **kwargs)
        return cc, out.getvalue()

    @staticmethod
    def _invoked(cc):
        return [call.args[0] for call in cc.call_args_list]

    def test_runs_all_phases_in_order(self):
        cc, _ = self._run()
        self.assertEqual(
            self._invoked(cc),
            ['scrape_news', 'link_news_stories',
             'reclassify_news_articles', 'build_news_digest'],
        )
        run = ScrapeJobRun.objects.get(job__slug='news.pipeline')
        self.assertEqual(run.status, ScrapeJobRun.SUCCESS)
        self.assertEqual(
            set(
                ScrapeJobRunItem.objects.filter(
                    run=run, status=ScrapeJobRunItem.DONE,
                ).values_list('item__key', flat=True)
            ),
            {'scrape', 'link', 'reclassify', 'digest'},
        )

    def test_second_invocation_skips_done_phases(self):
        self._run()
        cc, _ = self._run()
        cc.assert_not_called()
        # Both invocations open a run; the second finishes
        # SUCCESS with nothing to do.
        self.assertEqual(ScrapeJobRun.objects.count(), 2)
        latest = ScrapeJobRun.objects.latest('id')
        self.assertEqual(latest.status, ScrapeJobRun.SUCCESS)

    def test_fresh_reruns_every_phase(self):
        self._run()
        cc, _ = self._run(fresh=True)
        self.assertEqual(len(cc.call_args_list), 4)
        # --fresh is forwarded to scrape_news only — the other
        # phases need no flag.
        self.assertEqual(
            cc.call_args_list[0].args, ('scrape_news', '--fresh')
        )
        self.assertEqual(
            cc.call_args_list[1].args, ('link_news_stories',)
        )

    def test_failure_aborts_and_resumes_at_failed_phase(self):
        with patch(f'{self.MODULE}.call_command') as cc:
            cc.side_effect = [None, CommandError('boom')]
            with self.assertRaises(CommandError):
                call_command('news_pipeline', stdout=StringIO())
        self.assertEqual(
            self._invoked(cc),
            ['scrape_news', 'link_news_stories'],
        )
        run = ScrapeJobRun.objects.get()
        self.assertEqual(run.status, ScrapeJobRun.PARTIAL)
        statuses = {
            ri.item.key: ri.status
            for ri in ScrapeJobRunItem.objects.filter(run=run)
        }
        self.assertEqual(statuses['scrape'], ScrapeJobRunItem.DONE)
        self.assertEqual(statuses['link'], ScrapeJobRunItem.FAILED)
        # The next same-cycle invocation retries the failed
        # phase and everything after it — scrape stays DONE.
        cc, _ = self._run()
        self.assertEqual(
            self._invoked(cc),
            ['link_news_stories', 'reclassify_news_articles',
             'build_news_digest'],
        )

    def test_from_phase_skips_earlier_phases(self):
        cc, _ = self._run(from_phase='digest')
        self.assertEqual(self._invoked(cc), ['build_news_digest'])

    def test_from_unknown_phase_errors(self):
        with self.assertRaises(CommandError):
            self._run(from_phase='bogus')

    def test_dry_run_prints_pending_and_writes_nothing(self):
        cc, out = self._run(dry_run=True)
        cc.assert_not_called()
        self.assertIn('scrape', out)
        self.assertIn('digest', out)
        self.assertEqual(ScrapeJob.objects.count(), 0)
        self.assertEqual(ScrapeJobItem.objects.count(), 0)
        self.assertEqual(ScrapeJobRun.objects.count(), 0)
        self.assertEqual(ScrapeJobRunItem.objects.count(), 0)

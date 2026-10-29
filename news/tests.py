"""Tests for the news app — RSS parsing, idempotent upsert,
keyword topic classification, story clustering, digest build."""
import hashlib
from datetime import timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone

from scrape_jobs.models import ScrapeJobItem
from scrape_jobs.runner import ScrapeJobRunner

from .classification import classify_topic
from .clustering import link_unmatched_articles
from .digest import build_digest
from .models import (
    NewsArticle,
    NewsDigest,
    NewsSource,
    NewsStory,
    NewsTopic,
)
from .scraper import NewsScraper

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


def _response(data):
    return SimpleNamespace(data=data)


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
        # plus year boilerplate. The Jaccard reaches the
        # candidate band, but auto-merge requires a second
        # substantive shared stem, so the link is held for
        # admin review instead of auto-merging state vs
        # municipal budgets.
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
        self.assertEqual(a2.story_match_status, 'candidate')
        self.assertEqual(a2.story_id, a1.story_id)

    def test_old_articles_are_out_of_scope(self):
        old = _article(
            self.a, 'Ļoti vecs virsraksts par neko',
            published=self.now - timedelta(days=30),
        )
        stats = link_unmatched_articles(days=2)
        old.refresh_from_db()
        self.assertIsNone(old.story_id)
        self.assertEqual(stats['new_stories'], 0)


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

"""Tests for the news app — RSS parsing, idempotent upsert,
keyword topic classification, story clustering, digest build."""
import hashlib
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from scrape_jobs.models import (
    ScrapeJobItem,
    ScrapeJobRun,
    ScrapeJobRunItem,
)
from scrape_jobs.runner import (
    ScrapeJobRunner,
    cycle_scrape_exists,
)

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

    def test_candidate_member_does_not_inflate_story(self):
        # Same date-boilerplate setup as the candidate test: a2
        # links as 'candidate', so the story must keep counting
        # only the confirmed member (a1).
        a1 = _article(
            self.a, 'Valsts budžets 2027. gadam',
            published=self.now,
        )
        _article(
            self.b, 'Pašvaldību budžets 2027. gadam',
            published=self.now,
        )
        link_unmatched_articles(days=2)
        a1.refresh_from_db()
        a1.story.refresh_from_db()
        self.assertEqual(a1.story.source_count, 1)

    def test_auto_merge_uses_best_qualifying_member_title(self):
        # The argmax member title scores 0.60 but shares only
        # one substantive stem (the rest is 'gada'/'gadu' date
        # boilerplate); a second member title scores 0.50 with
        # three substantive shared stems — that one clears the
        # auto-merge bar, so the link is 'auto', not demoted to
        # 'candidate' by the argmax title alone.
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

    def test_detail_page_renders_confirmed_members_only(self):
        story = self._story('Ziņa viens', 5.0, source=self.a)
        cand = _article(
            self.b, 'Kandidāts (B)', topic=self.topic,
            story=story, story_match_status='candidate',
        )
        build_digest(self.today, top_n=5)
        response = self.client.get(
            f'/news/{self.today.isoformat()}/'
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Ziņa viens', content)
        self.assertNotIn(cand.title, content)


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
        in_lead = classify_topic('Ziņa', 'Grantu konkursā.', [topic])
        self.assertEqual(in_title, topic)
        self.assertEqual(in_lead, topic)


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

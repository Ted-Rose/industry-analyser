"""RSS feed scraper for Latvian news outlets.

Flow per source: fetch feed_url -> parse <item>s -> in-session
dedup on external_id -> unsaved NewsArticle rows (topic
classified) -> bulk create/update. No enrichment, no paid AI.

Runner/checkpoint precedent: tv_programs/scraper.py —
sync_items keyed by source.slug, yield inside try/except so a
fetch/parse failure thrown back into the generator records the
item failed and iteration continues with the next source.
"""
import hashlib
import logging
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from django.utils import timezone

from core_scraper.base import BaseScraper
from .classification import classify_topic
from .feeds import NEWS_FEEDS
from .models import NewsArticle, NewsSource, NewsTopic
from .topics import TOPICS

logger = logging.getLogger('news')


def _localname(tag):
    """ElementTree tag without an optional {namespace} prefix."""
    return tag.rsplit('}', 1)[-1].lower()


def _child_text(item, name):
    """Text of the first child element named ``name`` (namespace
    tolerant), stripped; '' when absent."""
    for child in item:
        if _localname(child.tag) == name:
            return (child.text or '').strip()
    return ''


def _child(item, name):
    for child in item:
        if _localname(child.tag) == name:
            return child
    return None


def _strip_html(raw):
    """Strip HTML markup from a feed description, keeping text."""
    if not raw:
        return ''
    return BeautifulSoup(raw, 'html.parser').get_text().strip()


def _parse_pubdate(raw):
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


class NewsScraper(BaseScraper):
    """Polls enabled NewsSource RSS feeds into NewsArticle rows."""

    def __init__(self, runner=None, dry_run=False, source_slug=None):
        self.enrich_search_results = False
        self.validate_result = False
        self.runner = runner
        self.dry_run = dry_run
        self.source_slug = source_slug
        self._active_source = None
        self.topics = list(NewsTopic.objects.filter(is_enabled=True))
        if self.dry_run and not self.topics:
            # Unseeded DB under --dry-run: classify against
            # unsaved seed rows so output stays realistic.
            self.topics = [NewsTopic(**t) for t in TOPICS]
        super().__init__()
        self.default_domain = 'news'
        # BaseScraper appends here when enrich_result returns a
        # falsy value (unused — enrich is disabled).
        self.excluded_resources = []

    def _enabled_sources(self):
        sources = list(NewsSource.objects.filter(is_enabled=True))
        if not sources and self.dry_run:
            sources = [
                NewsSource(**feed)
                for feed in NEWS_FEEDS
                if feed.get('is_enabled', True)
            ]
        if self.source_slug:
            sources = [s for s in sources if s.slug == self.source_slug]
        return sources

    def get_search_urls(self):
        sources = self._enabled_sources()
        runner = getattr(self, 'runner', None)
        if runner is None:
            for source in sources:
                self._active_source = source
                yield source.feed_url
            return

        # Runner path: each source feed is one checkpointed item.
        entries = [
            (source.slug, f'{source.name} RSS feed', 0, source)
            for source in sources
        ]
        items = runner.sync_items(entries)
        for item in runner.pending_items(items):
            source = item.obj
            try:
                self._active_source = source
                yield source.feed_url
                runner.touch()
            except Exception as e:
                runner.item_failed(item, e)
                continue
            runner.item_done(item)

    def parse_results(self, response):
        """Parse an RSS 2.0 feed body into a list of item dicts.

        Tolerates a dead fetch (response=None) and malformed XML
        — both yield an empty list.
        """
        if response is None:
            return []
        try:
            root = ElementTree.fromstring(response.data)
        except ElementTree.ParseError as e:
            label = getattr(
                self._active_source, 'slug', '?'
            )
            logger.warning(
                'Failed to parse feed %s as XML: %s', label, e
            )
            return []

        strategy = getattr(
            self._active_source, 'category_strategy', 'none'
        )
        results = []
        for el in root.iter():
            if _localname(el.tag) != 'item':
                continue
            parsed = self._parse_item(el, strategy)
            if parsed is not None:
                results.append(parsed)
        logger.info(
            'Parsed %d item(s) from feed %s',
            len(results),
            getattr(self._active_source, 'slug', '?'),
        )
        return results

    def _parse_item(self, item, strategy):
        title = _child_text(item, 'title')
        link = _child_text(item, 'link')
        guid = _child_text(item, 'guid')
        if not link and guid:
            # guid is commonly the article permalink.
            link = guid
        if guid:
            external_id = guid[:64]
        elif link:
            external_id = hashlib.sha256(
                link.encode()
            ).hexdigest()[:32]
        else:
            logger.warning('Skipping item with no guid and no link')
            return None

        description = _strip_html(_child_text(item, 'description'))
        pub_raw = (
            _child_text(item, 'pubdate')
            or _child_text(item, 'date')
        )
        published_at = _parse_pubdate(pub_raw)

        enclosure = _child(item, 'enclosure')
        image_url = (
            (enclosure.get('url') or '').strip()
            if enclosure is not None
            else ''
        )

        if strategy == 'tag':
            categories = [
                (c.text or '').strip()
                for c in item
                if _localname(c.tag) == 'category'
                and (c.text or '').strip()
            ]
        elif strategy == 'url':
            segs = [
                s for s in urlparse(link).path.split('/') if s
            ]
            categories = segs[1:3]
        else:
            categories = []

        return {
            'external_id': external_id,
            'link': link,
            'title': title,
            'lead': description,
            'image_url': image_url,
            'published_at': published_at,
            'feed_categories': categories,
        }

    def remove_redundant_results(self, results):
        """In-session dedup on external_id — a repeated guid inside
        one feed body is kept once."""
        seen = set()
        deduped = []
        for result in results:
            external_id = result['external_id']
            if external_id in seen:
                continue
            seen.add(external_id)
            deduped.append(result)
        removed = len(results) - len(deduped)
        if removed:
            logger.info('Removed %d duplicate item(s).', removed)
        return deduped

    def initiate_resources(self, results):
        """Build unsaved NewsArticle instances; topic is classified
        here so both new and refreshed rows carry it."""
        return [self.initiate_resource(r) for r in results]

    def initiate_resource(self, result):
        topic = classify_topic(
            result.get('title'), result.get('lead'), self.topics
        )
        return NewsArticle(
            source=self._active_source,
            external_id=result['external_id'][:64],
            link=result.get('link') or '',
            title=(result.get('title') or '')[:500],
            lead=result.get('lead') or '',
            image_url=(result.get('image_url') or '')[:600],
            published_at=result.get('published_at'),
            feed_categories=result.get('feed_categories') or [],
            topic=topic,
        )

    def create_or_update_resources(self, articles):
        """Bulk upsert per feed call: existing (source, external_id)
        rows get title/lead/categories/topic refreshed and
        last_seen bumped; the rest are inserted."""
        if not articles:
            return
        existing = {
            a.external_id: a
            for a in NewsArticle.objects.filter(
                source=self._active_source,
                external_id__in=[
                    a.external_id for a in articles
                ],
            )
        }
        now = timezone.now()
        to_update = []
        to_create = []
        for article in articles:
            row = existing.get(article.external_id)
            if row is None:
                to_create.append(article)
                continue
            row.title = article.title
            row.lead = article.lead
            row.link = article.link
            row.image_url = article.image_url
            row.published_at = article.published_at
            row.feed_categories = article.feed_categories
            row.topic = article.topic
            row.last_seen = now
            to_update.append(row)

        if self.dry_run:
            logger.info(
                '[dry-run] would create %d and update %d article(s)',
                len(to_create), len(to_update),
            )
            return
        if to_update:
            NewsArticle.objects.bulk_update(
                to_update,
                [
                    'title', 'lead', 'link', 'image_url',
                    'published_at', 'feed_categories', 'topic',
                    'last_seen',
                ],
            )
        if to_create:
            NewsArticle.objects.bulk_create(
                to_create, ignore_conflicts=True,
            )
        logger.info(
            'Feed %s: %d new, %d updated article(s)',
            getattr(self._active_source, 'slug', '?'),
            len(to_create), len(to_update),
        )

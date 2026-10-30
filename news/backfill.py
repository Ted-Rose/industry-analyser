"""Historical news backfill — sitemap and archive walkers.

Where NewsScraper polls RSS feeds for current articles,
NewsBackfillScraper walks each source's historical listings
(sitemap files or an archive page-walk) backwards and creates
NewsArticle rows for everything the daily feed can no longer
see.

One ScrapeJobItem per (source, listing-partition) under the
'news.backfill' job slug with a constant 'backfill' cycle key,
so a wall-clock-bounded execution can be re-invoked until every
partition is DONE. Design contract: docs/plans/
news_backfill_plan.md.

Two hard rules protect the rest of the pipeline:

* created rows always carry ``published_at`` — an undateable
  article is skipped, because a NULL date would enter today's
  story-clustering window via ``first_seen``;
* dedup is hash + link, two keys: sitemap rows get
  ``external_id = sha256(link)[:32]`` (the same fallback the
  feed parser uses) AND match existing rows on raw or
  normalized ``link``, so a feed-ingested row is never
  duplicated by its sitemap listing.
"""
import hashlib
import json
import logging
import re
from abc import ABC, abstractmethod
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from django.db.models import Q
from django.utils import timezone

from scrape_jobs.models import ScrapeJobItem

from .models import NewsArticle
from .scraper import (
    NewsScraper,
    _child,
    _child_text,
    _localname,
    _parse_pubdate,
    _strip_html,
)

logger = logging.getLogger('news')


@dataclass
class Partition:
    """One listing chunk — one ScrapeJobItem of the backfill job.

    ``key`` becomes the item-key suffix ('2026-W44',
    'sitemap-4', 'post-1'), ``url`` the listing URL to fetch
    (sitemap file or archive page). ``start``/``end`` bound the
    partition's article dates where the strategy knows them —
    ``--since``/``--until`` compare against them; unbounded
    partitions (flat chunk files) are never date-filtered.
    """
    key: str
    label: str
    url: str
    start: date | None = None
    end: date | None = None
    meta: dict = field(default_factory=dict)


def parse_sitemap_xml(data):
    """Parse a sitemap body -> ``(kind, entries)``.

    ``kind`` is 'index', 'urlset' or None (malformed/unknown
    root). Entries are ``{'loc', 'lastmod', 'news_pubdate'}``
    dicts — news_pubdate holds the Google News
    ``<news:publication_date>`` where present, '' otherwise.
    Namespace-tolerant via the same _localname idiom the feed
    parser uses.
    """
    if not data:
        return None, []
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as e:
        logger.warning('Failed to parse sitemap XML: %s', e)
        return None, []
    kind = _localname(root.tag)
    if kind == 'sitemapindex':
        kind, child_name = 'index', 'sitemap'
    elif kind == 'urlset':
        child_name = 'url'
    else:
        return None, []
    entries = []
    for el in root:
        if _localname(el.tag) != child_name:
            continue
        news = _child(el, 'news')
        entries.append({
            'loc': _child_text(el, 'loc'),
            'lastmod': _child_text(el, 'lastmod'),
            'news_pubdate': (
                _child_text(news, 'publication_date')
                if news is not None
                else ''
            ),
        })
    return kind, entries


# Query params stripped by normalize_link — feeds and sitemaps
# disagree on tracking decoration often enough that the dedup
# lookup must see through it.
_TRACKING_PARAMS = {'fbclid', 'gclid', 'mc_cid', 'mc_eid'}


def normalize_link(url):
    """Canonical form for the dedup lookup only — the raw
    sitemap link is still what gets stored. Lowercases
    scheme+host, drops the fragment, utm_*/tracker params and a
    single trailing slash."""
    parts = urlparse(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith('utm_')
        and k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path
    if len(path) > 1 and path.endswith('/'):
        path = path[:-1]
    return urlunparse((
        parts.scheme.lower(),
        parts.netloc.lower(),
        path,
        '',
        urlencode(query),
        '',
    ))


class BackfillStrategy(ABC):
    """How one source's historical listing is walked.

    ``earliest`` is the source's known archive floor. The
    scraper always calls ``enumerate_partitions`` with
    ``until`` = today — never the user's ``--until`` — so the
    synced item set is the full range: sync_items deactivates
    every active item it does not see, and is_active is
    admin-owned. ``--since``/``--until`` narrow processing only.
    """

    earliest = None

    @abstractmethod
    def enumerate_partitions(self, scraper, source, until):
        """Partition objects newest-first. May make HTTP calls
        through ``scraper.make_request`` (index fetches)."""
        raise NotImplementedError

    def skip_link(self, link):
        """Listing locs that are not article pages — override in
        strategies whose files mix in non-article URLs."""
        return False

    def iter_article_urls(self, scraper, partition):
        """Fetch the partition's sitemap listing ->
        ``[{'link', 'news_pubdate'}]``.

        A dead fetch (make_request exhausted its retries and
        returned None) raises — the partition item fails and is
        retried next run. A fetched-but-unparseable or empty
        listing still yields [], completing the partition."""
        response = scraper.make_request(partition.url)
        if response is None:
            raise RuntimeError(
                f'{partition.key}: listing fetch failed '
                f'({partition.url}) — retries exhausted'
            )
        entries = scraper.parse_results(response)
        return [
            {'link': e['link'], 'news_pubdate': e['news_pubdate']}
            for e in entries
        ]

    def _month_partitions(self, source, until, url_for):
        """Newest-first monthly partitions from ``until``'s
        month back to ``self.earliest``'s."""
        year, month = until.year, until.month
        floor = (self.earliest.year, self.earliest.month)
        partitions = []
        while (year, month) >= floor:
            first = date(year, month, 1)
            last = date(year, month, monthrange(year, month)[1])
            key = f'{year}-{month:02d}'
            partitions.append(Partition(
                key=key,
                label=f'{source.name} articles {key}',
                url=url_for(year, month, first, last),
                start=first,
                end=last,
                meta={'first': first, 'last': last},
            ))
            if month == 1:
                year, month = year - 1, 12
            else:
                month -= 1
        return partitions


class WeekSitemapStrategy(BackfillStrategy):
    """One sitemap file per ISO week (lsm, lsm-en)."""

    def __init__(self, url_pattern, earliest):
        self.url_pattern = url_pattern
        self.earliest = earliest

    def enumerate_partitions(self, scraper, source, until):
        monday = until - timedelta(days=until.weekday())
        floor = (
            self.earliest
            - timedelta(days=self.earliest.weekday())
        )
        partitions = []
        while monday >= floor:
            iso = monday.isocalendar()
            key = f'{iso.year}-W{iso.week:02d}'
            partitions.append(Partition(
                key=key,
                label=f'{source.name} articles {key}',
                url=self.url_pattern.format(
                    year=iso.year, week=iso.week,
                ),
                start=monday,
                end=monday + timedelta(days=6),
            ))
            monday -= timedelta(days=7)
        return partitions


class MonthSitemapStrategy(BackfillStrategy):
    """One sitemap file per calendar month (delfi, jauns)."""

    def __init__(self, url_pattern, earliest):
        self.url_pattern = url_pattern
        self.earliest = earliest

    def enumerate_partitions(self, scraper, source, until):
        return self._month_partitions(
            source, until,
            lambda year, month, first, last: (
                self.url_pattern.format(year=year, month=month)
            ),
        )


class ChunkProbeSitemapStrategy(BackfillStrategy):
    """Flat ``sitemap-{n}.xml`` chunks, enumerated n descending
    (diena, db). The range is a probed ceiling — a chunk that
    404s or fails to parse simply yields zero URLs and still
    completes item_done. Chunks carry no date bounds, so
    ``--since``/``--until`` never filter them. ``exclude_loc``
    drops non-article locs (diena's /arhivs/ day listings)."""

    def __init__(self, url_pattern, n_range, exclude_loc=None):
        self.url_pattern = url_pattern
        self.n_range = sorted(n_range, reverse=True)
        self.exclude_loc = exclude_loc

    def skip_link(self, link):
        return (
            self.exclude_loc is not None
            and self.exclude_loc.search(link) is not None
        )

    def enumerate_partitions(self, scraper, source, until):
        return [
            Partition(
                key=f'sitemap-{n}',
                label=f'{source.name} sitemap chunk {n}',
                url=self.url_pattern.format(n=n),
            )
            for n in self.n_range
        ]


class SitemapIndexStrategy(BackfillStrategy):
    """Sitemap index -> child sitemaps as partitions (ir,
    rebaltica). Index URLs are discovered from robots.txt
    ``Sitemap:`` lines with ``https://<host>/sitemap.xml`` as
    the fallback; the first index that yields a child matching
    ``child_regex`` wins. ``child_regex`` may carry ``year`` and
    ``part`` named groups — year is filtered to
    [earliest.year, until.year] and both feed ``key_format``."""

    def __init__(self, host, child_regex, earliest,
                 key_format='{part}'):
        self.host = host
        self.child_regex = re.compile(child_regex)
        self.earliest = earliest
        self.key_format = key_format

    def _index_urls(self, scraper):
        urls = []
        response = scraper.make_request(
            f'https://{self.host}/robots.txt'
        )
        data = getattr(response, 'data', None) or b''
        for line in data.decode('utf-8', 'replace').splitlines():
            if line.lower().startswith('sitemap:'):
                urls.append(line.split(':', 1)[1].strip())
        fallback = f'https://{self.host}/sitemap.xml'
        if fallback not in urls:
            urls.append(fallback)
        return urls

    def enumerate_partitions(self, scraper, source, until):
        children = []
        for index_url in self._index_urls(scraper):
            response = scraper.make_request(index_url)
            kind, entries = parse_sitemap_xml(
                getattr(response, 'data', None)
            )
            if kind != 'index':
                continue
            for entry in entries:
                match = self.child_regex.search(entry['loc'])
                if match is None:
                    continue
                groups = match.groupdict()
                year = (
                    int(groups['year'])
                    if groups.get('year')
                    else None
                )
                part = (
                    int(groups['part'])
                    if groups.get('part')
                    else None
                )
                if year is not None and not (
                    self.earliest.year <= year <= until.year
                ):
                    continue
                children.append((year, part, entry['loc']))
            if children:
                break
        if not children:
            # Zero matching children means discovery failed
            # (dead index, non-XML error page) — raising fails
            # the run before sync_items, where returning []
            # would deactivate every existing item instead.
            raise RuntimeError(
                f'{source.slug}: no sitemap index yielded '
                f'children matching '
                f'{self.child_regex.pattern!r}'
            )
        children.sort(
            key=lambda c: (c[0] or 0, c[1] or 0), reverse=True,
        )
        partitions = []
        for year, part, loc in children:
            key = self.key_format.format(year=year, part=part)
            start = date(year, 1, 1) if year else None
            end = date(year, 12, 31) if year else None
            partitions.append(Partition(
                key=key,
                label=f'{source.name} articles {key}',
                url=loc,
                start=start,
                end=end,
            ))
        return partitions


class ArchiveMonthStrategy(BackfillStrategy):
    """lvportals monthly archive — HTML listing page-walk, no
    sitemap. ``iter_article_urls`` GETs lapa:1,2,... until a
    page adds no new article hrefs (a soft-repeat or an empty
    page), capped at ``max_pages`` per month."""

    url_pattern = (
        'https://lvportals.lv/arhivs/lapa:{page}'
        '/kartot:jaunakais/no:{first}/lidz:{last}'
    )
    max_pages = 50
    # Article hrefs are '/<section>/<id>-<slug>' with a 5+
    # digit id — author/tag/theme links never reach it.
    article_href = re.compile(r'^/[a-z0-9-]+/\d{5,}-')

    def __init__(self, earliest):
        self.earliest = earliest

    def enumerate_partitions(self, scraper, source, until):
        def url_for(year, month, first, last):
            return self.url_pattern.format(
                page=1,
                first=first.strftime('%d.%m.%Y'),
                last=last.strftime('%d.%m.%Y'),
            )
        return self._month_partitions(source, until, url_for)

    def iter_article_urls(self, scraper, partition):
        first = partition.meta['first']
        last = partition.meta['last']
        # The walk is up to ``max_pages`` throttled fetches —
        # --max-minutes must cut it mid-month too. A
        # deadline-cut walk sets budget_exhausted so the
        # partition stays pending and is re-walked next run
        # rather than marked DONE on a partial listing.
        deadline_passed = getattr(
            scraper, '_deadline_passed', lambda: False
        )
        seen = set()
        entries = []
        for page in range(1, self.max_pages + 1):
            if deadline_passed():
                scraper.budget_exhausted = True
                logger.info(
                    'Deadline reached inside %s page-walk '
                    'after %d page(s) — partition stays pending',
                    partition.key, page - 1,
                )
                break
            url = self.url_pattern.format(
                page=page,
                first=first.strftime('%d.%m.%Y'),
                last=last.strftime('%d.%m.%Y'),
            )
            response = scraper.make_request(url)
            if response is None:
                # Retries exhausted — NOT an empty page. Fails
                # the partition item (first page or mid-walk)
                # so the month retries next run instead of
                # burning to DONE on a transient outage.
                raise RuntimeError(
                    f'{partition.key}: archive page {page} '
                    'fetch failed — retries exhausted'
                )
            new = [
                link for link in self._article_links(response)
                if link not in seen
            ]
            if not new:
                break
            seen.update(new)
            entries.extend(
                {'link': link, 'news_pubdate': None}
                for link in new
            )
        return entries

    def _article_links(self, response):
        data = getattr(response, 'data', None)
        if not data:
            return []
        soup = BeautifulSoup(data, 'html.parser')
        links = []
        for anchor in soup.find_all('a', href=True):
            href = anchor['href'].strip()
            path = urlparse(href).path if '://' in href else href
            if self.article_href.match(path):
                links.append(urljoin('https://lvportals.lv', path))
        return links


BACKFILL_STRATEGIES = {
    'lsm': WeekSitemapStrategy(
        'https://www.lsm.lv/assets/sitemap/'
        'news_lv_{year}W{week:02d}.xml',
        earliest=date(2023, 11, 1),
    ),
    'lsm-en': WeekSitemapStrategy(
        'https://www.lsm.lv/assets/sitemap/'
        'news_en_{year}W{week:02d}.xml',
        earliest=date(2023, 11, 1),
    ),
    'delfi': MonthSitemapStrategy(
        'https://www.delfi.lv/sitemap/news/'
        '{year}-{month:02d}/index.xml',
        earliest=date(2013, 6, 1),
    ),
    # jauns answers 200 for arbitrary months — the path date is
    # a cache key — so the month's 1st day fills both slots and
    # empty/mismatched urlsets are tolerated downstream.
    'jauns': MonthSitemapStrategy(
        'https://jauns.lv/sitemap/{year}{month:02d}01/'
        'articles/{year}_{month:02d}.xml',
        earliest=date(2012, 1, 1),
    ),
    'diena': ChunkProbeSitemapStrategy(
        'https://www.diena.lv/sitemap-{n}.xml',
        range(1, 16),
        # sitemap-13 lists /arhivs/ day-listing pages, not
        # articles — day-page coverage is a planned follow-up.
        # Skipping the locs (rather than capping the probe at
        # n=12) keeps any future chunk above 13 in scope.
        exclude_loc=re.compile(r'/arhivs/'),
    ),
    'db': ChunkProbeSitemapStrategy(
        'https://www.db.lv/sitemap-{n}.xml',
        range(1, 9),
    ),
    'ir': SitemapIndexStrategy(
        'ir.lv',
        r'sitemap_articles_(?P<year>\d{4})_(?P<part>\d+)',
        earliest=date(2010, 1, 1),
        key_format='{year}-{part:02d}',
    ),
    'rebaltica': SitemapIndexStrategy(
        'rebaltica.lv',
        r'wp-sitemap-posts-post-(?P<part>\d+)',
        earliest=date(2016, 1, 1),
        key_format='post-{part}',
    ),
    'lvportals': ArchiveMonthStrategy(earliest=date(2008, 1, 1)),
    # tvnet and apollo are absent on purpose: no historical
    # listing — feed + news-sitemap cover only ~1-2 days.
}

_ARTICLE_TYPES = {
    'article', 'newsarticle', 'reportagenewsarticle',
}

# Last-resort publish dates embedded in article URLs. Sitemap
# ``lastmod`` is deliberately NOT a candidate — it is
# update-time, not publish-time.
_URL_DATE_REGEXES = {
    'lsm': re.compile(
        r'(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})'
    ),
    'lsm-en': re.compile(
        r'(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})'
    ),
    'diena': re.compile(
        r'/(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})(/|$)'
    ),
}


def _meta_content(soup, attr, name):
    tag = soup.find('meta', attrs={attr: name})
    if tag is None:
        return ''
    return (tag.get('content') or '').strip()


def _jsonld_article(soup):
    """First JSON-LD node typed Article/NewsArticle/
    ReportageNewsArticle, walking @graph and top-level lists."""
    for script in soup.find_all(
        'script', attrs={'type': 'application/ld+json'}
    ):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else [data]
        candidates = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            graph = node.get('@graph')
            if isinstance(graph, list):
                candidates.extend(graph)
            candidates.append(node)
        for node in candidates:
            if not isinstance(node, dict):
                continue
            types = node.get('@type') or []
            if isinstance(types, str):
                types = [types]
            if _ARTICLE_TYPES & {
                str(t).lower() for t in types
            }:
                return node
    return None


def _jsonld_image(node):
    image = node.get('image')
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get('url')
    return (image or '').strip() if isinstance(image, str) else ''


def _url_date(url, source_slug):
    regex = _URL_DATE_REGEXES.get(source_slug)
    if regex is None:
        return None
    match = regex.search(urlparse(url).path)
    if match is None:
        return None
    try:
        parsed = datetime(
            int(match.group('year')),
            int(match.group('month')),
            int(match.group('day')),
        )
    except ValueError:
        return None
    return timezone.make_aware(parsed)


def extract_article_metadata(html_bytes, url, source_slug,
                             category_strategy='none'):
    """Article page -> metadata dict for NewsArticle fields.

    ``published_at`` resolves JSON-LD ``datePublished`` ->
    ``article:published_time`` -> per-source URL-date regex.
    None of them is the sitemap ``lastmod`` — and None is
    allowed to propagate: the scraper drops undateable rows.
    """
    soup = BeautifulSoup(html_bytes or b'', 'html.parser')
    title = ''
    lead = ''
    image_url = ''
    published_at = None

    node = _jsonld_article(soup)
    if node is not None:
        title = (node.get('headline') or '').strip()
        lead = _strip_html(node.get('description') or '')
        image_url = _jsonld_image(node)
        published_at = _parse_pubdate(node.get('datePublished'))

    title = title or _meta_content(soup, 'property', 'og:title')
    if not lead:
        lead = _strip_html(
            _meta_content(soup, 'property', 'og:description')
            or _meta_content(soup, 'name', 'description')
        )
    image_url = image_url or _meta_content(
        soup, 'property', 'og:image'
    )
    if published_at is None:
        published_at = _parse_pubdate(
            _meta_content(soup, 'property', 'article:published_time')
        )
    if published_at is None:
        published_at = _url_date(url, source_slug)

    if category_strategy == 'url':
        segs = [s for s in urlparse(url).path.split('/') if s]
        categories = segs[1:3]
    else:
        categories = []

    return {
        'title': title,
        'lead': lead,
        'image_url': image_url,
        'published_at': published_at,
        'feed_categories': categories,
    }


class NewsBackfillScraper(NewsScraper):
    """Walks per-source historical listings into NewsArticle.

    Item granularity is one (source, listing-partition);
    article-level progress inside a partition is not
    checkpointed — an interrupted partition retries whole and
    the hash/link dedup makes the retry cheap.
    """

    def __init__(self, runner=None, dry_run=False,
                 source_slug=None, since=None, until=None,
                 deadline=None):
        super().__init__(
            runner=runner, dry_run=dry_run, source_slug=source_slug,
        )
        self.since = since
        self.until = until or timezone.localdate()
        self.deadline = deadline
        self.budget_exhausted = False
        self._active_partition = None
        self._active_strategy = None

    def _deadline_passed(self):
        return (
            self.deadline is not None
            and timezone.now() >= self.deadline
        )

    def _partition_in_range(self, partition):
        if (
            self.since is not None
            and partition.end is not None
            and partition.end < self.since
        ):
            return False
        if (
            self.until is not None
            and partition.start is not None
            and partition.start > self.until
        ):
            return False
        return True

    def _planned_sources(self):
        """(planned, failed) for every enabled source that has
        a strategy — never narrowed by --source: sync_items
        must see the full set.

        ``planned`` holds ``(source, strategy, partitions)``;
        ``partitions`` is None when enumeration failed (a dead
        sitemap index), and ``failed`` collects the
        ``(source, exception)`` pairs."""
        sources = self._enabled_sources()
        if self.source_slug and not any(
            s.slug == self.source_slug for s in sources
        ):
            logger.warning(
                '--source %r matches no enabled source',
                self.source_slug,
            )
        planned = []
        failed = []
        for source in sources:
            strategy = BACKFILL_STRATEGIES.get(source.slug)
            if strategy is None:
                logger.info(
                    'Skipping %s: no historical listing — feed '
                    '+ news-sitemap cover ~1-2 days',
                    source.slug,
                )
                continue
            # Enumeration always runs against today, never
            # --until: the partitions feed sync_items, which
            # deactivates every active item it does not see —
            # and is_active is admin-owned, never re-enabled.
            # A narrow --until would permanently deactivate the
            # out-of-range items (a future --until typo would
            # likewise mint permanently-DONE future partitions);
            # --since/--until narrow processing only, via
            # _partition_in_range.
            try:
                partitions = strategy.enumerate_partitions(
                    self, source, timezone.localdate(),
                )
            except Exception as e:
                # A dead index must not fail the run before
                # sync_items — that would block every healthy
                # source's work. The source's existing item
                # keys are synced as obj=None placeholders (not
                # deactivated, skipped at processing time) and
                # the failure is re-raised at the end of
                # get_search_urls so the run still ends FAILED.
                logger.error(
                    '%s: partition enumeration failed: %s',
                    source.slug, e,
                )
                failed.append((source, e))
                partitions = None
            planned.append((source, strategy, partitions))
        return planned, failed

    def _placeholder_entries(self, source):
        """sync_items entries keeping a dead-index source's
        existing items active without processing them —
        obj=None is skipped by the pending loop and stays
        pending for the next run."""
        prefix = f'{source.slug}:'
        items = ScrapeJobItem.objects.filter(
            job__slug=self.runner.slug,
            key__startswith=prefix,
        )
        return [
            (item.key, item.label, item.priority, None)
            for item in items
        ]

    def _raise_enumeration_failure(self, failed):
        """Re-raise a collected enumeration error so the run
        still ends FAILED — placeholder entries only protect
        the dead source's items, they do not hide the outage."""
        slugs = ', '.join(source.slug for source, _ in failed)
        _, exc = failed[0]
        raise RuntimeError(
            f'partition enumeration failed for {slugs}: {exc}'
        ) from exc

    def get_search_urls(self):
        runner = self.runner
        planned, failed = self._planned_sources()

        if runner is None:
            for source, strategy, partitions in planned:
                if partitions is None:
                    # Enumeration failed — nothing to yield;
                    # raised below after healthy sources.
                    continue
                if (
                    self.source_slug
                    and source.slug != self.source_slug
                ):
                    continue
                for partition in partitions:
                    if not self._partition_in_range(partition):
                        continue
                    if self._deadline_passed():
                        self.budget_exhausted = True
                        if failed:
                            self._raise_enumeration_failure(
                                failed
                            )
                        return
                    self._active_source = source
                    self._active_strategy = strategy
                    self._active_partition = partition
                    yield partition.url
            if failed:
                self._raise_enumeration_failure(failed)
            return

        # One sync for ALL sources' partitions — entries must
        # enumerate the full range or sync_items deactivates
        # every item it does not see. A source whose
        # enumeration failed contributes its existing item
        # keys as obj=None placeholders instead.
        entries = []
        for source, strategy, partitions in planned:
            if partitions is None:
                entries.extend(self._placeholder_entries(source))
                continue
            entries.extend(
                (
                    f'{source.slug}:{partition.key}',
                    partition.label,
                    0,
                    (source, strategy, partition),
                )
                for partition in partitions
            )
        items = runner.sync_items(entries)
        for item in runner.pending_items(items):
            if item.obj is None:
                # Placeholder for a source whose enumeration
                # failed this pass — stays pending, retried
                # on the next invocation.
                continue
            source, strategy, partition = item.obj
            if self.source_slug and source.slug != self.source_slug:
                # Filtered out by --source: neither done nor
                # failed — stays pending for the next pass.
                continue
            if not self._partition_in_range(partition):
                # --since/--until narrow processing, never the
                # synced set — the item stays pending too.
                continue
            if self._deadline_passed():
                self.budget_exhausted = True
                logger.info(
                    'Backfill budget exhausted before %s — '
                    'stopping', item.key,
                )
                break
            try:
                self._active_source = source
                self._active_strategy = strategy
                self._active_partition = partition
                yield partition.url
                runner.touch()
            except Exception as e:
                runner.item_failed(item, e)
                continue
            if self.budget_exhausted:
                # The deadline hit inside initiate_resources —
                # the in-flight partition is NOT done; its
                # remaining articles retry (deduped) next run.
                break
            runner.item_done(item)
        if failed:
            # A dead index was absorbed above to keep the
            # source's items active and other sources working —
            # the run must still report the outage as FAILED.
            self._raise_enumeration_failure(failed)

    def scrape_portal(self, partition_url):
        """Fetch the partition's article-URL list through the
        active strategy, dedup it in-session, then split/fetch
        via initiate_resources."""
        strategy = self._active_strategy
        if strategy is None:
            return []
        entries = strategy.iter_article_urls(
            self, self._active_partition,
        )
        results = []
        for entry in entries:
            link = (entry.get('link') or '').strip()
            if not link or strategy.skip_link(link):
                continue
            results.append({
                # Same fallback id as NewsScraper._parse_item —
                # a 32-char sha256 prefix of the link.
                'external_id': hashlib.sha256(
                    link.encode()
                ).hexdigest()[:32],
                'link': link[:600],
                'news_pubdate': entry.get('news_pubdate'),
            })
        deduped = self.remove_redundant_results(results)
        self.last_search_had_results = bool(deduped)
        if not deduped:
            logger.info('No results found for %s', partition_url)
            return []
        return self.initiate_resources(deduped)

    def parse_results(self, response):
        """Sitemap body -> ``[{'link', 'news_pubdate'}]`` —
        replaces the parent's RSS parse. A dead fetch, a
        malformed body or a non-urlset document yields []."""
        kind, entries = parse_sitemap_xml(
            getattr(response, 'data', None)
        )
        if kind != 'urlset':
            return []
        return [
            {
                'link': entry['loc'],
                'news_pubdate': entry['news_pubdate'],
            }
            for entry in entries
            if entry['loc']
        ]

    def initiate_resources(self, results):
        """Two-key DB dedup then per-URL page fetch.

        Known rows (external_id hash OR raw/normalized link)
        get a bulk last_seen bump and are never refetched — a
        link-matched row keeps its guid external_id. Unknown
        URLs are fetched one by one; ``published_at`` is
        mandatory (news_pubdate -> page metadata -> URL-date
        regex) because a NULL date would enter today's
        clustering window via first_seen.
        """
        if not results:
            return []
        source = self._active_source
        new_results = []
        # The id/link lookup runs in slices — a ~45k-URL chunk
        # sitemap would otherwise blow past the DB driver's
        # bind-parameter limit.
        for slice_start in range(0, len(results), 4000):
            new_results.extend(
                self._dedup_slice(
                    source, results[slice_start:slice_start + 4000]
                )
            )
        logger.info(
            'Partition %s: %d known link(s) skipped, %d new',
            getattr(self._active_partition, 'key', '?'),
            len(results) - len(new_results),
            len(new_results),
        )
        articles = []
        fetches = 0
        skipped = 0
        for index, result in enumerate(new_results):
            if self._deadline_passed():
                self.budget_exhausted = True
                logger.info(
                    'Backfill budget exhausted inside %s — %d '
                    'URL(s) deferred to the next run, %d '
                    'skipped so far',
                    getattr(self._active_partition, 'key', '?'),
                    len(new_results) - index,
                    skipped,
                )
                break
            try:
                response = self.make_request(result['link'])
            except Exception as e:
                # One malformed <loc> (e.g. a URL urllib3
                # rejects synchronously) must not fail the
                # partition — every retry would re-hit the
                # same URL and never reach DONE.
                skipped += 1
                logger.warning(
                    'Skipping %s: fetch raised %s',
                    result['link'], e,
                )
                continue
            fetches += 1
            # ~500-URL partitions run 10+ min — the heartbeat
            # must beat the runner's stale-run sweep.
            if self.runner is not None and fetches % 25 == 0:
                self.runner.touch()
            if getattr(response, 'status', None) != 200:
                skipped += 1
                logger.info(
                    'Skipping %s: fetch status %s',
                    result['link'],
                    getattr(response, 'status', None),
                )
                continue
            try:
                meta = extract_article_metadata(
                    response.data,
                    result['link'],
                    source.slug,
                    getattr(source, 'category_strategy', 'none'),
                )
                published_at = (
                    _parse_pubdate(result.get('news_pubdate'))
                    or meta['published_at']
                )
            except Exception as e:
                skipped += 1
                logger.warning(
                    'Skipping %s: metadata extract raised %s',
                    result['link'], e,
                )
                continue
            if published_at is None:
                skipped += 1
                logger.info(
                    'Skipping undateable article %s',
                    result['link'],
                )
                continue
            result.update(meta)
            result['published_at'] = published_at
            try:
                articles.append(self.initiate_resource(result))
            except Exception as e:
                # A classify_topic/NewsArticle failure on one
                # URL must not fail the whole partition.
                skipped += 1
                logger.warning(
                    'Skipping %s: article init raised %s',
                    result['link'], e,
                )
                continue
        return articles

    def _dedup_slice(self, source, results):
        """One dedup query over a <=4000-result slice: rows
        matching by external_id hash OR raw/normalized link get
        a bulk last_seen bump; the rest come back for fetching."""
        known_ids = set()
        known_links = set()
        if source is not None and source.pk is not None:
            ids = [r['external_id'] for r in results]
            links = [r['link'] for r in results]
            candidates = links + [
                normalize_link(link) for link in links
            ]
            known = (
                NewsArticle.objects.filter(source=source)
                .filter(
                    Q(external_id__in=ids)
                    | Q(link__in=candidates)
                )
            )
            known_pks = []
            for pk, external_id, link in known.values_list(
                'pk', 'external_id', 'link'
            ):
                known_pks.append(pk)
                known_ids.add(external_id)
                known_links.add(link)
            if known_pks:
                if self.dry_run:
                    logger.info(
                        '[dry-run] would bump last_seen on %d '
                        'known article(s)',
                        len(known_ids | known_links),
                    )
                else:
                    # pk__in reuses the already-evaluated match
                    # set — re-filtering on ids+links would
                    # issue the same ~12k-bind OR query twice.
                    NewsArticle.objects.filter(
                        pk__in=known_pks
                    ).update(last_seen=timezone.now())
        return [
            r for r in results
            if r['external_id'] not in known_ids
            and r['link'] not in known_links
            and normalize_link(r['link']) not in known_links
        ]

    def initiate_resource(self, result):
        article = super().initiate_resource(result)
        article.is_backfill = True
        return article

    def partition_listing(self):
        """--dry-run lines: '[dry-run] <slug>: <partition> <n>'.

        Enumerates each filtered source's partitions and counts
        listing URLs; the lvportals page-walk is not exercised
        (months print '?' instead).
        """
        for source in self._enabled_sources():
            if self.source_slug and source.slug != self.source_slug:
                continue
            strategy = BACKFILL_STRATEGIES.get(source.slug)
            if strategy is None:
                yield (
                    f'[dry-run] {source.slug}: no historical '
                    'listing — feed + news-sitemap cover ~1-2 '
                    'days'
                )
                continue
            self._active_source = source
            self._active_strategy = strategy
            # Same contract as _planned_sources: enumerate the
            # full [earliest, today] range and let
            # _partition_in_range apply --since/--until. A dead
            # index only degrades this source's output — the
            # listing continues with the remaining sources.
            try:
                partitions = strategy.enumerate_partitions(
                    self, source, timezone.localdate()
                )
            except Exception as e:
                yield (
                    f'[dry-run] {source.slug}: enumeration '
                    f'failed: {e}'
                )
                continue
            for partition in partitions:
                if not self._partition_in_range(partition):
                    continue
                if isinstance(strategy, ArchiveMonthStrategy):
                    yield (
                        f'[dry-run] {source.slug}: '
                        f'{partition.key} ?'
                    )
                    continue
                try:
                    entries = strategy.iter_article_urls(
                        self, partition
                    )
                except Exception as e:
                    yield (
                        f'[dry-run] {source.slug}: '
                        f'{partition.key} fetch failed: {e}'
                    )
                    continue
                # Mirror scrape_portal's filter — skip_link
                # locs (diena's /arhivs/ day listings) are
                # never fetched, so they must not count.
                count = len([
                    e for e in entries
                    if (e.get('link') or '').strip()
                    and not strategy.skip_link(e['link'].strip())
                ])
                yield (
                    f'[dry-run] {source.slug}: '
                    f'{partition.key} {count}'
                )

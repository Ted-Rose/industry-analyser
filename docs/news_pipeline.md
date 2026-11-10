# News pipeline — scraping, topic classification, clustering & scoring

How the `news/` app turns Latvian RSS feeds into the daily ranked
digest at `/news/`. Covers the whole path end to end, with the
three stages the doc title names called out in depth. Written
against the code — where a docstring references a plan file
(`docs/plans/news_digest_plan.md`, `news_backfill_plan.md`,
`news_audio_plan.md`), that file is not in the repo; the closest
design doc is `openspec/changes/add-news-digest-google-task/`.

Zero paid AI calls anywhere in this pipeline — classification
and clustering are pure Python heuristics, deliberately.

## In plain words

Once a day, `news_pipeline` runs on the maintainer's machine
(not Cloud Run) and does four things in order, checkpointing
each so a crash resumes where it left off:

1. **Collect.** Fetch each enabled outlet's RSS feed with a
   "only if it changed" conditional GET. Every `<item>` becomes
   a `NewsArticle` row (title, lead, link, image, publish
   date). Already-seen articles just get a "still there"
   timestamp; only new ones go further.
2. **Tag.** Keyword-match each new article's title+lead
   against curated lists for six topics (economics, politics,
   government-funding, war, diplomacy, crime). Words are
   squashed to 4-char stems so Latvian declensions collapse;
   a title hit counts double and score ≥ 2 is required. No
   hits → the article stays untopicked (`topic = NULL`).
3. **Cluster.** Group articles that are the same story
   reported by different outlets: compare each unmatched
   article's title stems against titles in stories dated
   ±1 day (Jaccard similarity). Close enough → join the
   story; otherwise start a new one. Each story's
   `importance_score` = distinct outlets × topic weight ×
   average outlet weight.
4. **Rank.** Pick the day's stories that have an enabled
   topic — or no topic but ≥2 outlets — sort by importance,
   keep the top 20. The headline comes from the highest-
   weighted outlet that covered it; the rationale is just
   "N outlets: lsm, delfi, …".

## Orchestration

`news_pipeline` is the single daily entry point — one
`local:daily` entry in `run_all_jobs`' `JOBS` list and the
command the maintainer's schedule should fire. It runs the
four phases in order under job slug `news.pipeline` (daily
UTC cycle), each phase checkpointed as a `ScrapeJobItem`
(`scrape`/`link`/`reclassify`/`digest`) so a re-invocation in
the same cycle resumes at the first unfinished phase and a
fully-DONE cycle is a no-op — the feeds are scraped from the
maintainer's machine and the pipeline **never runs on Cloud
Run**:

```
scrape_news → link_news_stories → reclassify_news_articles
  (articles)    (stories)           (topic retag)
            → build_news_digest
              (ranked digest)
```

A phase that raises is recorded FAILED, later phases do not
run and the run ends PARTIAL — the next invocation retries
that phase. The phases are plain `call_command` invocations,
so each delegated command keeps its own behavior and stays
usable standalone:

```bash
python manage.py news_pipeline [--fresh] [--from PHASE] \
    [--dry-run]
python manage.py seed_news_sources [--sync] [--dry-run]
python manage.py scrape_news [--source SLUG] [--fresh] \
    [--dry-run] [--ignore-cooldown] \
    [--backfill [--since D] [--until D] [--max-minutes N]]
python manage.py link_news_stories [--days N] [--dry-run]
python manage.py build_news_digest [--date D] [--top-n N] \
    [--dry-run]
python manage.py reclassify_news_articles [--all] [--days N] \
    [--dry-run] [--batch-size N]
```

`news_pipeline --fresh` re-runs every phase and forwards
`--fresh` to `scrape_news` so feeds are re-fetched;
`--from PHASE` resumes at a named phase; `--dry-run` prints
the pending phases without invoking anything or writing job
bookkeeping. After a multi-day outage, articles older than
`link_news_stories --days 2`'s window stay unmatched — run
`link_news_stories --days N` once to catch up, and
`build_news_digest --date D` to backfill a missed day's
digest.

## Data model (`news/models.py`)

| Table | Role |
|---|---|
| `news_source` | One RSS feed per outlet: `feed_url`, `language`, `is_enabled`, `category_strategy` (`tag`/`url`/`none`), `importance_weight`, `etag`/`last_modified` conditional-GET validators |
| `news_topic` | Interest topic: `keywords` (JSON list of Latvian keyword specs), `weight`, `is_enabled` |
| `news_article` | One feed item: `(source, external_id)` unique, `link`, `title`, `lead`, `image_url`, `published_at`, `feed_categories`, `is_backfill`, `topic` FK, `story` FK + `story_match_status`/`story_match_score` |
| `news_story` | Cluster of same-story articles across outlets: `title`, `topic` FK, `published_date`, `source_count`, `importance_score` |
| `news_digest` / `news_digest_item` | One day + ranked items (`rank`, `headline`, `rationale`) |
| `news_digest_task` | Link row for the Google Tasks hook (dedup + audit) |
| `news_source_preference` | Per-user outlet ranking for the story reader |
| `news_article_audio` | TTS seam — table and endpoint exist, no generator yet |

`story_match_status` values: `unmatched` → `auto` / `manual`,
plus legacy `candidate` rows — the clusterer no longer produces
`candidate` links (see Stage 3); the existing ones await admin
review and never count as coverage anywhere downstream.
`CONFIRMED_MATCH_STATUSES = ('auto', 'manual')`.

## Stage 1 — RSS scraping (`news/scraper.py`, `news/feeds.py`)

`scrape_news` seeds sources/topics (`ensure_seeded` —
`get_or_create` only, admin edits survive; `seed_news_sources
--sync` is the explicit "adopt new seed keyword lists" switch),
then runs `NewsScraper` under a `ScrapeJobRunner` with job slug
`news.feeds`. One `ScrapeJobItem` per enabled source, so a
killed run resumes per-feed. The cooldown gate skips the run
when a SUCCESS already exists this cycle locally (default
cycle = today UTC) or within 1 day on GCP; `--fresh`,
`--ignore-cooldown`, `--dry-run` and `--source` bypass it
(`--source` runs are marked PARTIAL so they don't satisfy the
gate for a later full pass).

Per source feed:

1. **Conditional GET.** The source's stored `etag` /
   `last_modified` go out as `If-None-Match` /
   `If-Modified-Since`. A 304 short-circuits the item as done —
   nothing is parsed. Only a 200 body refreshes the stored
   validators (an error page's ETag must not wrongly 304 the
   feed later), and a validator the server stopped sending is
   cleared. `--fresh`/`--source` omit the headers so the feed
   is always re-parsed. Editing `feed_url` clears the
   validators via `NewsSource.save()` — a different resource
   could legitimately answer 304 to them.
2. **Parse `<item>`s** (namespace-tolerant ElementTree):
   - `external_id` = `<guid>` truncated to 64 chars, else
     `sha256(link)[:32]`;
   - `link` = `<link>`, or an http-looking `<guid>`; items
     with no usable href are skipped;
   - `lead` = `<description>` with HTML stripped
     (BeautifulSoup; plain text only gets `html.unescape`);
   - `published_at` = `<pubDate>` (RFC-2822) or `<dc:date>`
     (ISO-8601); naive results are localized;
   - `image_url` = `<enclosure url>`, when present;
   - `feed_categories` per `category_strategy`: `tag` →
     `<category>` texts; `url` → link path segments `[1:3]`;
     `none` → empty. (Categories are stored metadata, not a
     classification input.)
3. **In-session dedup** on `external_id`.
4. **Split known/new** (`initiate_resources`): one query for
   the feed's known `external_id`s — known rows get a single
   bulk `last_seen` UPDATE and are skipped entirely (no
   re-classify, no field rewrite); only new items go through
   topic classification and `NewsArticle` instantiation.
5. **Bulk upsert** (`create_or_update_resources`):
   `bulk_update` title/lead/link/image/published_at/
   feed_categories/topic/last_seen on existing rows,
   `bulk_create(..., ignore_conflicts=True)` the rest.

No detail-page enrichment (`enrich_search_results=False`), no
per-item HTTP beyond the feed fetch itself.

## Stage 2 — topic classification (`news/classification.py`, `news/topics.py`)

Pure-Python keyword scoring over `title + lead`. Runs inside
`initiate_resource`, i.e. only for rows being created or
updated — `reclassify_news_articles` re-runs it on existing
rows (default: `topic IS NULL` only; `--all` re-scores
everything).

**Tokenization.** Text is NFKC-lowercased, `\w+`-tokenized and
cut to 4-char prefix stems (`STEM_LEN = 4` — crude, but
collapses Latvian declensions like "budžetu"/"budžets" without
a stemmer dependency). Pure-digit stems are dropped.
Classification deliberately runs with `drop_stopwords=False`
so multi-word keywords like "ES fondi" can rely on the `es`
stem — with the tradeoff that a stem keyword on a
stopword-prefix root (e.g. `līdzfinansējums` → `līdz`) would
fire on the preposition, which is why curated `=`/`*` forms
exist.

**Keyword word-specs** (each whitespace-separated word of a
`NewsTopic.keywords` entry):

| Form | Kind | Matches |
|---|---|---|
| `=word` | exact | the literal token, unstemmed (`=Latvenergo` ≠ `Latvijas`) |
| `word*` | prefix | any token starting with `word` |
| `word` | stem | the word's 4-char stem in the text's stem set |

A keyword hits when **all** its word-specs match
(order-independent) — "ES fondi" needs both `es` and `fond`.
A word that reduces to a pure digit stem yields no spec, so a
keyword reduced to nothing is skipped.

**Scoring.** Each keyword that hits anywhere in title+lead
scores +1; if it also hits fully inside the title alone it
scores +1 more. The topic with the highest total wins; ties
resolve to the first topic in pk order (callers order topics
by pk so the tie-break is deterministic). Zero hits → `topic =
NULL` — untopicked articles are stored but can never appear in
the digest (see below).

**Seed topics** (`TOPICS` in `topics.py`): `economics` (1.2),
`politics` (1.0), `government-funding` (1.3), `war` (1.1),
`diplomacy` (1.0), `crime` (0.4 — deliberately last in the
tuple and lowest-weighted: tagging a crime story demotes it
below the NULL-topic effective weight of 1.0 rather than
hiding it). The keyword lists are heavily curated —
4-char stems are greedy on short roots (`eiro`→`eiro` hits all
`Eiropas*`, `banka`→`bank` hits `bankomāts`, `karš` declensions
must be `=`-exact so `karalis`/`karuselis` don't hit). Read the
comment block at the top of `topics.py` before editing seed
keywords; a keyword duplicated across two topics double-scores
both.

`reclassify_news_articles` additionally recomputes each touched
story's `topic` (most common non-null topic among confirmed
members) and re-runs `_refresh_story` so the new topic weight
flows into `importance_score`.

## Stage 3 — story clustering (`news/clustering.py`)

`link_news_stories` (default `--days 2`) assigns `unmatched`
articles from the last N days to `NewsStory` clusters. Article
day = `published_at.date()`, falling back to `first_seen.date()`
when undated (which is exactly why backfill skips undateable
articles — a NULL date would leak into today's window).

**Blocking.** Candidate stories are those with `published_date`
within ±1 day of the article's day (precedent:
`classified_ads/property_matcher.py`).

**Similarity.** Jaccard (`|A∩B| / |A∪B|`) over the stopword-
filtered 4-char-stem set of the article title vs. each member
article's title (fallback: the story title). Stopwords and
numeric stems are dropped for this comparison — unlike
classification, which keeps stopwords.

**Outcomes** (constants at the top of `clustering.py`):

- score ≥ `AUTO_THRESHOLD` (0.30) **and** ≥
  `MIN_SHARED_SUBSTANTIVE` (2) shared stems that aren't date
  boilerplate → `story_match_status='auto'`;
- otherwise a fresh `NewsStory` is created from the article
  (title, lead, topic, `published_date` = article day) and the
  article is linked `'auto'` with a NULL score.

There is no `CANDIDATE_THRESHOLD` anymore — the clusterer
produces only `'auto'` links, so near-misses become their own
stories instead of piling up in a review queue. The
`'candidate'` status survives only on rows written before the
thresholds were merged; they still count as coverage nowhere
until an admin flips them to `'manual'`.

"Substantive" means shared stems minus `_DATE_STEMS`
(`gada`/`gadu`/`gadā`/`gads`) — the guard exists because same-
year boilerplate otherwise glues distinct stories together
("Valsts budžets 2027. gadam" vs "Pašvaldību budžets 2027.
gadam" would score 0.50 on `budž+gada` alone). `_best_story`
ranks member titles by `(meets the auto bar, score, substantive
count)` so a title that clears the auto bar on its own beats a
higher-scoring title whose overlap is only boilerplate. An
article whose title stems to nothing can't match anything and
becomes its own story rather than staying `unmatched` forever.

**Story refresh** (`_refresh_story`, after every link):

```
source_count     = # distinct sources among confirmed members
importance_score = source_count
                 × (topic.weight or 1.0)
                 × mean(member.source.importance_weight)
```

Only `auto`/`manual` members count — `candidate` links must not
inflate either field. A story with zero confirmed members
degrades to 0/0. The mean is over member *articles* (an outlet
with two articles weighs twice in the mean but once in
`source_count`).

## Relevance scoring — the weights behind the numbers

Two admin-editable weights feed `importance_score`:

- **`NewsSource.importance_weight`** — how much an outlet's
  coverage counts. Seed values (`feeds.py`): IR and Re:Baltica
  1.3; LSM, Diena, DB, LV portāls 1.2; Delfi, TVNET, Apollo
  1.0; Jauns.lv 0.5 (tabloid); LSM English 1.0 but disabled.
- **`NewsTopic.weight`** — editorial interest per topic:
  government-funding 1.3, economics 1.2, war 1.1,
  politics/diplomacy 1.0, crime 0.4.

So a story covered by 3 outlets averages their source weights,
multiplied by its topic's weight — breadth of coverage first,
outlet quality second, topic interest third.

**Digest selection** (`build_digest`): stories with
`published_date == date` and ≥1 confirmed member that either
have an *enabled* topic **or** have `topic IS NULL` with
`source_count >= 2` — multi-outlet coverage is itself strong
importance evidence, while single-source untopicked
singletons (sports/celebrity noise) stay excluded. Ranked by
`-importance_score`, `-last_seen`, top N (default 20).
Headline = the confirmed member article from the highest-
weighted source (tie: longest lead); rationale =
`"N outlets: lsm, delfi, …"` recomputed from live membership.
Rebuilds are idempotent (`update_or_create` + wholesale item
replace inside a transaction), then a best-effort Google Tasks
hook fires outside the transaction — deduped by the
`NewsDigestTask` link row, never able to fail the build, and
inert unless `GOOGLE_OAUTH_CLIENT_JSON` is set. Recipients are
the enabled `NewsDigestSubscription` rows — one task per
subscriber in their own Google account.

**Per-user ordering** (`preferences.py`): `ordered_sources`
sorts a user's `NewsSourcePreference` ranks first, then
`-importance_weight, pk`; `ordered_story_articles` presents a
story's member articles in that order — the "favorite outlet
that covered it" is what the story card leads with. Anonymous
users get the plain weight ordering.

## Backfill — `scrape_news --backfill` (`news/backfill.py`)

`NewsBackfillScraper` subclasses `NewsScraper` and walks each
source's *historical* listings (sitemaps or archive pages)
under job slug `news.backfill` with constant cycle key
`backfill` — re-invocations resume the same DONE partition set
across days.

- **Strategies** (`BACKFILL_STRATEGIES`): `lsm`/`lsm-en` weekly
  sitemap files, `delfi`/`jauns` monthly sitemaps,
  `diena`/`db` probed `sitemap-N.xml` chunks, `ir`/`rebaltica`
  sitemap-index walks, `lvportals` an archive month page-walk.
  `tvnet`/`apollo` have no historical listing and are skipped.
- **Partition = one ScrapeJobItem.** `enumerate_partitions`
  always runs against today (never `--until`) so `sync_items`
  sees the full range — `--since`/`--until` only narrow which
  pending partitions process. A dead sitemap index is synced
  as placeholders, not deactivated, and the failure is
  re-raised so the run still ends FAILED.
- **Two-key dedup** in 4000-URL slices: `external_id =
  sha256(link)[:32]` *and* match on raw or normalized `link`
  (`normalize_link` strips fragment, utm_*/tracker params,
  scheme/host case, one trailing slash) — a feed-ingested row
  is never duplicated by its sitemap listing. Known rows get a
  `last_seen` bump; the rest are fetched page by page.
- **`published_at` is mandatory.** Resolution order:
  sitemap `<news:publication_date>` → JSON-LD `datePublished`
  → `article:published_time` meta → per-source URL-date regex.
  Undateable articles are skipped. Backfilled rows carry
  `is_backfill=True` and are topic-classified via the
  inherited `initiate_resource`.
- `--max-minutes` ends the run PARTIAL on budget exhaustion
  (the constant cycle key means the next invocation resumes);
  `--dry-run` lists partitions without fetching articles.

## Surfaces

- `/news/` and `/news/<date>/` — server-rendered digest inside
  the SPA shell (crawlers without JS read the same HTML).
- `/news/rss.xml` — outgoing RSS feed, last 7 days
  (`news/syndication.py`).
- `sitemap.xml`, `llms.txt` — crawler/agent surfaces
  (`news/views.py`).
- `/api/news/` — digests, story cards, audio, preferences
  (`news/api.py`), consumed by `frontend/src/news/`.
- `/news/article/<pk>/audio/` — TTS seam (`news/audio.py`;
  gTTS → GCS signed URL when `GCS_AUDIO_BUCKET` is set).
- Admin: `NewsArticle` `story_match_status` is the review
  queue for `candidate` links (flip to `manual` to confirm);
  topics/sources/digests are all admin-editable.

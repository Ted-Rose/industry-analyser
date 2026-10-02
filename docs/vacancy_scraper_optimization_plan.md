# Vacancy Scraper — Smarter Scraping Plan

Analysis of `fetcher/management/commands/scrape_vacancies.py`,
`fetcher/scraper.py`, `core_scraper/base.py`, `scrape_jobs/runner.py`
and the cv.lv API (verified live, ~15 requests).

## tl;dr

- **The per-keyword search loop is redundant.** The cv.lv search API
  accepts a `categories[]` filter with enum values such as
  `INFORMATION_TECHNOLOGY`. One request
  (`?limit=1000&categories[]=INFORMATION_TECHNOLOGY`) returns all
  ~374 IT vacancies **with full `positionContent`** — everything the
  keyword matcher needs. Verified live: total = 374, `offset`
  pagination works, multiple categories OR together
  (IT + QUALITY_ASSURANCE → 439).
- **Same-vacancy re-writes are the real cost today**: 108 searchable
  keywords → 108 search requests → every vacancy is re-fetched,
  re-`save()`d and its M2M rows re-`add()`ed once per keyword that
  returns it. `remove_redundant_results()` is a no-op despite its
  comment saying it should dedup within the session.
- **`Vacancy.job_portal_id` already exists** (unused by the scraper,
  populated only by the legacy `/fetcher/` view) — perfect for the
  "which portal found this" flag, no migration needed.
- **likeit.lv code paths can be pruned**: the HTML `parse_results`
  branch (`div.show-expander-content`) and the generic
  `enrich_result`/`get_resource_info_link` fallback exist only for
  it. The legacy `/fetcher/` view reads `fetcher/config.json`, which
  no longer exists — it is already dead code.

## Current behavior (what actually happens)

`scrape_vacancies` loops over configured portal ids, builds a
`ScrapeJobRunner` per portal (`fetcher.vacancies.<pid>`, weekly ISO
cycle) and runs `VacancyScrapper`.

### Portal 1 — cv.lv API (`type: "api"`)

`_keyword_search_urls()` yields **one URL per `Keyword` with
`only_filter=False`**:

```
GET /api/v1/vacancy-search-service/search?limit=1000&keywords[]=<name>
```

Locally there are **108 searchable keywords → 108 requests** per
run. Each response is a page of vacancy dicts; `parse_results`
returns `data['vacancies']`; `remove_redundant_results` returns them
unmodified (its comment — "Remove already processed vacancy id's in
this session" — was never implemented). `initiate_resources` builds
unsaved `Vacancy` objects; `create_or_update_resources` then, per
batch:

- `Vacancy.objects.filter(vacancy_portal_id__in=batch)` + per-row
  `.get()` (N+1 queries),
- `existing.last_seen = now; existing.save()` — **one UPDATE per
  occurrence**. A vacancy surfaced by 10 keyword searches is saved
  10 times per run,
- per-vacancy loops of `industries.add()` / `keywords.add()` —
  per-pair INSERT attempts every single occurrence,
- `VacancyFile.objects.get_or_create` per vacancy with a file.

So the effective write volume is roughly
`vacancies × matching_keywords` per run — the "updates the same
resource multiple times" behavior observed.

### Portal 2 — cv.lv public site (`type: "nextjs"`)

`_get_nextjs_search_urls()` offset-paginates
`/lv/search?limit=…&offset=…&categories%5B0%5D=INFORMATION_TECHNOLOGY`
(SSR `__NEXT_DATA__` JSON — same vacancy objects as the API). This
path is **already category-based, not keyword-based**, and already
dedups detail fetches via `detail_fetched_at` (only new or
`renewedDate`-renewed ads are enriched; detail adds
`standardDetails` text + OCR of `fileDetails` attachments).

### Portal 3 — likeit.lv (HTML)

Dead portal. Its only footprint is the `BeautifulSoup` /
`div.show-expander-content` branch in `parse_results` and the
non-nextjs `enrich_result` → `super().enrich_result()` →
`get_resource_info_link` fallback.

## cv.lv API schema (verified)

OpenAPI specs are served at
`https://www.cv.lv/api/doc/v3/api-docs/swagger-config`; the
`vacancy-search` spec documents
`GET /api/v1/vacancy-search-service/search` with parameters:

| Param | Type | Verified |
|---|---|---|
| `categories[]` | enum strings (`INFORMATION_TECHNOLOGY`, `QUALITY_ASSURANCE`, …, 32 values) | ✅ `?categories[]=INFORMATION_TECHNOLOGY` → `total: 374`; OR semantics for multiple values |
| `keywords[]` | string array | already used |
| `limit`, `offset` | int | ✅ `offset=3` shifts the window |
| `towns[]`, `counties[]`, `countries[]`, `languages[]` | int arrays | spec only |
| `workTimes[]` | enum (`FULL_TIME`, `PART_TIME`, …) | spec only |
| `remoteWorkType` | `ON_SITE`/`HYBRID`/`FULLY_REMOTE` | spec only |
| `salaryFrom`, `isHourlySalary`, `domain` (EE/LV/LT), `employerId` | — | spec only |

Other notes:

- The search response embeds the full taxonomy counts under
  `categories` (`INFORMATION_TECHNOLOGY: 374`, …) plus lookup maps
  (`towns`, `counties`, `workTimes`, `languages`).
- Each vacancy carries `positionContent` (the whole description),
  `renewedDate`, `categories` (numeric ids — `10` appears to be IT),
  `keywords`, `skills`, `townId`, salary fields.
- There is **no public single-vacancy GET** in the spec
  (`vacancies-service` is the employer write API); detail data
  (`standardDetails`, attached files) only exists on the public
  `/lv/vacancy/{id}` pages — so the nextjs portal remains the only
  source for enrichment/OCR.
- A parallel `GET /api/v1/vacancies-service/search` exists with the
  same parameter set (untested; the vacancy-search-service endpoint
  is sufficient).

## Proposed changes

### 1. Replace the keyword loop with a category sweep (API portal)

Add `search_params` support to API portals (same config key the
nextjs portal already uses) and paginate `offset` until
`offset >= total` (the response already returns `total` — parse it
like `_search_total` does for nextjs). With `limit=1000` this is
**one request** for all 374 IT vacancies.

```
?limit=1000&offset=0&categories[]=INFORMATION_TECHNOLOGY
```

Concretely in `scraper.py`:

- `_keyword_search_urls()` → `_api_search_urls()`, mirroring the
  nextjs generator: yield
  `f"{base}?limit={limit}&offset={offset}&{search_params}"`,
  stop on empty page or `offset >= total` (store `total` from the
  JSON response in `parse_results`, like `_search_total`).
- Checkpointing: the whole sweep becomes a single `search`
  `ScrapeJobItem` — identical to the nextjs item pattern (drop the
  per-keyword `sync_items`). Resume semantics get coarser but match
  the nextjs portal; a failed sweep simply re-runs next cycle.
- Keep a config escape hatch: if a portal has no `search_params`,
  fall back to the current keyword loop (or simply don't — decide
  once, see "Open questions").

Keywords are **already applied locally** by
`_find_keywords_in_content()` over title + `positionContent` +
employer + detail/OCR text — they never needed to be search
queries. `Keyword.only_filter` keeps its meaning (filter-only vs.
matching) and nothing else changes in the tagging pipeline.

**Effect**: 108 requests → 1–2 per run; result volume drops to one
copy of each vacancy.

### 2. In-memory dedup (`self._seen_ids`)

Implement what `remove_redundant_results` already advertises:

```python
def __init__(...):
    self._seen_ids = set()

def remove_redundant_results(self, results):
    fresh = [r for r in results if r.get('id') not in self._seen_ids]
    self._seen_ids.update(r.get('id') for r in fresh)
    return fresh
```

~2 000 ids is trivially bearable in memory, as noted. This kills
all duplicate downstream work even if overlapping searches ever
return (e.g. a keyword fallback). Cheap insurance either way.

### 3. Batch the `last_seen` "sighting" update

`create_or_update_resources` currently does
`existing.save()` per vacancy per batch. Instead:

```python
seen_ids = [v.vacancy_portal_id for v in existing_batch]
Vacancy.objects.filter(vacancy_portal_id__in=seen_ids) \
    .update(last_seen=timezone.now())
```

— one UPDATE per page instead of one per row. Only fall back to
`save()` for the rare rows that actually change (filled-in
`title`/`company_name`, new `detail_fetched_at`). Fixes the N+1
`existing_vacancies.get()` too — materialize the queryset once into
a dict keyed by `vacancy_portal_id`.

### 4. Batch M2M writes

Collect `(vacancy_id, keyword_id)` / `(vacancy_id, industry_id)`
pairs across the whole batch and `bulk_create` on the through
models with `ignore_conflicts=True`:

```python
VacancyContainsKeyword.objects.bulk_create(rows, ignore_conflicts=True)
VacancyIndustries.objects.bulk_create(rows, ignore_conflicts=True)
```

Two INSERTs per page replace the per-vacancy-per-keyword loop. The
existing `unique_together` constraints make this safe.

### 5. Record the source portal — reuse `job_portal_id`

`Vacancy.job_portal_id` (IntegerField, currently written only by the
legacy `/fetcher/` view, set on 37 482 of 48 183 local rows) is the
natural "which configured portal created this row" marker — set
`job_portal_id=self.portal_id` in `_build_vacancy`. No schema change.

Semantics: **portal that first created the row** (portal 1 and 2
share the cv.lv `vacancy_portal_id` namespace, so a row can't be
double-created anyway). If the later question is "was it *also*
seen via X", that can be derived per-run from scrape job logs; if
you want it on the row, a second field (`last_seen_via`) or a
comma-set is a small follow-up — but start with `job_portal_id`.

### 6. Portal order: public portal first, API second

Portal execution order is just `sorted(config keys)` — put the
nextjs portal's key before the API's (or add an `order` field).
Then per run:

1. **nextjs sweep** (`/lv/search`, IT category): creates new rows
   stamped `job_portal_id=2`, detail-fetches + OCRs new/renewed ads.
2. **API sweep** (`categories[]=INFORMATION_TECHNOLOGY`): for
   already-seen ids → `last_seen` bump only; for anything the
   public pages missed → create with `job_portal_id=1` (these get
   detail-enriched on the *next* nextjs run, since
   `detail_fetched_at` is null — `_needs_detail_fetch` already
   handles this).

After a few weeks, `job_portal_id=1 AND job_portal_id` rows created
recently tell you whether the API finds anything the public portal
doesn't. If it doesn't, the API portal can be disabled in config —
or kept as a cheap integrity check (it's 1 request).

Honest counterpoint, since the APIs return identical objects: the
API sweep alone (1 request) could replace the nextjs search pages
entirely for *discovery*, with nextjs detail pages fetched only for
enrichment. That would be even fewer requests, but it abandons the
"public site as source of truth" experiment and the SSR pages are
the only place `standardDetails`/file metadata exist — so keeping
the nextjs-first order you proposed is reasonable. Both directions
are a config-order change only once `search_params` is unified.

### 7. Prune likeit.lv and the dead HTML path

- Remove the portal from `fetcher/config_v2.json` **and** the
  `industry-analyser-fetcher-portals` secret (manual step — the
  secret is yours to update).
- Delete the `else` BeautifulSoup branch in `parse_results`
  (`div.show-expander-content`).
- Simplify `enrich_search_results`: it's `type != 'api'` today only
  because likeit lacked a type; becomes `type == 'nextjs'`.
- `enrich_result`'s non-nextjs fallback (`super().enrich_result`
  → `get_resource_info_link` + raw fetch) becomes unreachable —
  remove along with `get_resource_info_link` if nothing else calls
  it.
- Remove the legacy `/fetcher/` view (`fetcher.views.fetcher`):
  it reads `fetcher/config.json` which doesn't exist locally —
  it's already broken, bypasses `BaseScraper` throttling with raw
  `requests`, and duplicates the whole scrape flow. Drop the URL
  route, the view, and `save_or_update_keywords`. Keep
  `find_vacancies`, `add_keyword`, PWA views.
- Update `fetcher/README.md` / `ARCHITECTURE.md` / root `README.md`
  portal tables.

### 8. Industry tagging inconsistency (found while analyzing)

`_build_vacancy` matches `Industry.objects.filter(name=<numeric
category id>)` — works only because local `Industry` rows are named
`'1'`…`'20'`. The `industry_mapping` config (e.g. `"10": "it"`) —
used by the legacy view — is **ignored by the scraper**, so
scraper-created vacancies get industry `'10'` but never `'it'`,
and won't appear when filtering by `it` in the UI. Options:

- Apply `industry_mapping` in `_build_vacancy` (map each numeric
  category through the config, same as the old view), and/or
- Since the sweep is IT-only, unconditionally add the configured
  industry (e.g. `'it'`) to every vacancy the sweep returns.

Recommend the config-driven `industry_mapping` approach — it
survives adding more categories later.

## Resulting request/write profile

| | Before | After |
|---|---|---|
| API search requests/run | 108 (one per keyword) | 1–2 (category sweep) |
| nextjs search pages | ~4–10 | unchanged |
| Detail-page fetches | new/renewed only | unchanged |
| Vacancy UPDATEs/run | ≈ vacancies × matched keywords | 1 bulk UPDATE per page |
| M2M writes | per-row-per-occurrence | 2 bulk INSERTs per page |
| New fields needed | — | none (`job_portal_id` reused) |

## Suggested implementation order

1. `search_params` + offset pagination for API portals (drop the
   keyword loop) — biggest win, self-contained.
2. `_seen_ids` dedup + batched `last_seen`/M2M writes.
3. `job_portal_id` stamping + portal order swap (nextjs first).
4. `industry_mapping` fix.
5. likeit.lv + legacy `/fetcher/` view removal.
6. Doc updates; update the GCP secret.

Steps 1–5 are independent enough to land as separate commits/PRs.

## Open questions

- Keep a keyword-based API fallback for keywords that match
  *outside* IT (e.g. an `INDUSTRY` keyword relevant in other
  categories)? If yes, keep the old item generator behind a config
  flag; if IT-only is confirmed, delete it outright.
- Numeric `categories` on vacancies vs. enum filter names — is the
  mapping (10 → INFORMATION_TECHNOLOGY) published anywhere stable,
  or should `industry_mapping` in config remain the source of truth?
- Should `state`/`days_open` ever transition (vacancies stay
  `CREATED` forever today)? Out of scope, but worth noting.

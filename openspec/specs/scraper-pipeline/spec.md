# Scraper Pipeline Specification

## Purpose

Defines the shared scraping contract every portal scraper
implements by subclassing `core_scraper.base.BaseScraper`: the
`run()` → `scrape_portal()` → `create_or_update_resources()`
pipeline, the shared HTTP layer (retries, per-domain
throttling), pagination/sighting behavior, and the subclass
flag surface.

## Requirements

### Requirement: Pipeline dispatch

Every scraper SHALL subclass `BaseScraper` and drive work
through `run()`: it iterates `get_search_urls()`, calls
`scrape_portal(url)` per URL, and passes non-empty results to
`create_or_update_resources()`. `scrape_portal()` SHALL run
`make_request` → `parse_results` → `remove_redundant_results`
→ `extract_resources` in that order.

#### Scenario: A search URL produces resources

- **WHEN** `get_search_urls()` yields a URL whose page parses
  to results
- **THEN** `run()` calls `create_or_update_resources()` with
  the extracted resources once for that URL

#### Scenario: Failed portal is thrown back into the generator

- **WHEN** `scrape_portal()` raises and `get_search_urls()`
  returned a generator
- **THEN** `run()` calls `throw(exc)` on it so item-level
  checkpointing (e.g. ScrapeJobRunner) can record the failure
  and resume with the next item's first URL

#### Scenario: Failed portal with a plain iterable

- **WHEN** `scrape_portal()` raises and `get_search_urls()`
  returned a non-generator iterable
- **THEN** the exception re-raises and the run aborts

### Requirement: Shared HTTP layer

All scraping HTTP SHALL go through `self.make_request()`, which
uses one `urllib3.PoolManager` configured with
`Retry(total=3, backoff_factor=30, status_forcelist=[429, 500,
502, 503, 504])` and calls `self.sleep()` for per-domain
throttling before every request. Subclasses MUST NOT issue raw
`requests`/`urllib3` calls.

#### Scenario: Retries exhausted

- **WHEN** the PoolManager exhausts its retries
  (`MaxRetryError`)
- **THEN** `make_request()` logs the error, reports a
  warning-level Sentry event (`rate_limited` for 429, else
  `provider_error`) and returns `None`

#### Scenario: Per-domain throttle

- **WHEN** two requests target the same domain in quick
  succession
- **THEN** `sleep()` delays the second by the remainder of a
  ~1s interval (`min_seconds=max_seconds=1` by default)
  tracked per domain

### Requirement: Pagination and sightings

`scrape_portal()` SHALL set `last_search_had_results` from the
raw `parse_results` (not the pruned list), so subclasses keep
paginating while a page is non-empty even when every result is
a duplicate — sightings still get recorded for existing ads.
An empty page sets it to `False`.

#### Scenario: All-duplicate page keeps paginating

- **WHEN** a results page parses to only already-known ads
- **THEN** `last_search_had_results` stays `True` and the
  subclass's URL generator continues to the next page

#### Scenario: Redirect signals end of results

- **WHEN** the subclass sets `stop_on_redirect` and the
  response was served after a redirect
- **THEN** `scrape_portal()` treats it as the end of
  pagination: `last_search_had_results` becomes `False` and
  no resources are extracted

### Requirement: Subclass flag surface

`extract_resources()` SHALL branch on subclass flags:
`enrich_search_results` fetches each detail page via
`enrich_result()` (`get_resource_info_link` + `make_request`),
dropping falsy enrichments into `excluded_resources`;
`validate_result` routes enrichment through
`validate_and_return()`; `ai_analysis` sends each enriched
result to `analyse_and_save_resource()` instead of
`initiate_resource()`; without enrichment the whole batch goes
to `initiate_resources()`.

#### Scenario: Enrichment drops an unresolvable detail page

- **WHEN** `enrich_search_results` is set and `enrich_result()`
  returns a falsy value for a result
- **THEN** the result is appended to `excluded_resources` and
  excluded from the resource list

#### Scenario: Flags are declared in `__init__`

- **WHEN** a subclass configures its behavior
- **THEN** it MUST declare `enrich_search_results`,
  `validate_result`, and `excluded_resources` in `__init__`
  (no base default — `AttributeError` otherwise);
  `ai_analysis` and `stop_on_redirect` are base-initialized
  to `False` and only set when needed

#### Scenario: BlogScraper's sanctioned `run()` override

- **WHEN** a subclass needs pipeline behavior the flags
  cannot express
- **THEN** it MAY override `run()` — `BlogScraper` does so
  to make `MaxAPIRequestsReached` fatal-with-summary and
  skips `create_or_update_resources` because AI results
  save inline via `analyse_and_save_resource`

### Requirement: Refetch support

`refetch_single(resource)` SHALL fetch `resource.link` via
`make_request()` and return the dict produced by
`_parse_detail_for_refetch()` for partial updates; resources
without a `link` attribute or a failed fetch return `None`.

#### Scenario: Detail refetch succeeds

- **WHEN** a resource has a `link` and its detail page
  downloads
- **THEN** `refetch_single()` returns the parsed field dict
  the caller can bulk-update from

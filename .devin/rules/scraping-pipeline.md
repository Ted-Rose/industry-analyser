---
description: "Rules for writing/modifying scrapers and scrape management commands"
trigger: model_decision
---

When working on scrapers (`*/scraper.py`, `*scraper.py`,
`management/commands/`):

- Subclass `core_scraper.base.BaseScraper`; implement the abstract hooks
  (`parse_results`, `remove_redundant_results`, `initiate_resource(s)`,
  `create_or_update_resources`) rather than overriding `run()` unless
  control flow genuinely differs (`blogs` overrides `run()` only to
  catch `MaxAPIRequestsReached`).
- Always make HTTP calls through `self.make_request()` — it provides
  per-domain throttling and 429/5xx retries. No raw `requests`/urllib3
  calls, and keep `sleep()` intact: these are live third-party sites.
- Set the subclass flags explicitly in `__init__`:
  `enrich_search_results`, `validate_result`, `ai_analysis`,
  `excluded_resources`.
- Pagination must continue while a results page is non-empty so
  sightings get recorded even when every result is a duplicate.
- New bulk-update/refetch operations should subclass
  `BaseRefetchCommand` (`core_scraper/management/commands/base_refetch.py`)
  to inherit `--ids`/`--filter`/`--fields`/`--dry-run`/`--batch-size`.
- `blogs` Gemini calls are capped by `max_api_requests` in
  `blogs/config.yaml` — honor `MaxAPIRequestsReached`, don't remove the
  cap.

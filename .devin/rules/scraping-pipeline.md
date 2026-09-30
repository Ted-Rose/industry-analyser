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
- `blogs` AI calls go through `ai_providers`' `JobClient`
  (`JobClientBackend` in `blogs/ai_backends.py`), not
  `self.make_request()`: they are vendor SDK calls, not scraping HTTP,
  and are exempt from the "no raw `requests`/urllib3" rule. The request
  cap lives on the `AIJob` DB row (`max_requests_per_run`, editable in
  admin); a `max_api_requests` key left in `blogs/config.yaml` is
  deprecated — it only seeds the row on first creation and is ignored
  afterwards. Honor `MaxAPIRequestsReached`, don't remove the cap.

# Industry Analyser — Agent Guide

Django 5.2 / Python 3.12 monolith that scrapes Latvian web portals and
stores structured data for analysis. Deployed on GCP as a Cloud Run web
service plus scheduled Cloud Run jobs (region `europe-north1`).

Start with `DOCUMENTATION_INDEX.md` for the full doc map,
`LOCAL_SETUP.md` for setup, and `docs/` for design notes.

## App map

| Path | Purpose | Source |
|---|---|---|
| `fetcher/` | Job vacancy scraper; `/vacancies` UI, keyword matching | cv.lv (API), likeit.lv (HTML) |
| `classified_ads/` | Apartment/house rent & sale ads; `/classified-ads/` UI | ss.com |
| `blogs/` | Blog pages + Gemini AI theme analysis | spoki.lv |
| `tv_programs/` | TV schedule + heuristic movie classification; `/tv/` UI | tet.lv |
| `core_scraper/` | Shared `BaseScraper` ABC and `BaseRefetchCommand` ABC | — |
| `accounts/` | Stub app | — |
| `industry_analyser/` | Django project (settings, root urls, wsgi/asgi) | — |
| `terraform/` | GCP infra: Cloud Run jobs/service, Scheduler, Secret Manager | — |
| `scripts/` | One-off data-fix and job-entrypoint scripts | — |

## Scraper architecture

All scrapers subclass `core_scraper.base.BaseScraper`. The flow is:
`run()` → `get_search_urls()` → `scrape_portal()` → `parse_results()`
→ `remove_redundant_results()` → `extract_resources()` →
`create_or_update_resources()`.

Subclass flags control behavior: `enrich_search_results` (fetch each
detail page), `validate_result`, `ai_analysis` (Gemini), `bulk_save`.
HTTP goes through a shared `urllib3.PoolManager` with retries (429/5xx,
backoff 30s) and per-domain throttling in `sleep()` — never bypass it
with raw `requests`/`urllib3` calls in subclasses.

Key domain patterns:

- **Sightings**: `classified_ads` records one row per ad per day
  (`*Sighting` models, `unique_together(ad, seen_on)`); `days_active`
  counts sightings. Scrapers keep paginating while a results page is
  non-empty — even when all results are duplicates — so sightings are
  still recorded for existing ads.
- **Custom managers**: ad models' default `objects` manager hides
  `is_hidden=True` rows (and `is_sale_misclassified=True` on
  `ApartmentForRent`). Use `all_objects` in admin, refetch commands,
  and data-fix scripts. A `ModelAdmin` must override `get_queryset` to
  use `all_objects`, or flagged rows are invisible in admin
  (see `docs/django_notes.md`).
- **Refetch commands**: subclass `BaseRefetchCommand` to update existing
  rows by re-fetching detail pages. Common args: `--ids`, `--filter`
  (`"field__lookup=value"`), `--fields`, `--dry-run`, `--limit`,
  `--batch-size`.
- **AI cost control**: `blogs` uses two AI model tiers
  (`cheap`/`expensive`) assigned on the `blogs.theme_analysis` AIJob
  row, capped by its `max_requests_per_run` (admin-editable).
  Respect the cap; API calls cost money.

## AI layer

### PR-1: `ai_providers` data model + admin

The `ai_providers` app holds the AI configuration tables
(`ai_provider`, `ai_model`, `ai_job`, `ai_job_model`,
`ai_prompt_template`, `ai_input`, `ai_request`). The database is the
single source of truth for which provider/model each AI job uses —
Django admin is the UI, no yaml files or hardcoded model lists.
Runtime provider adapters and the job client land in later PRs.

### PR-4: JobClient runtime, job specs, seeding

`ai_providers.client.get_job_client(spec_or_slug,
max_requests_per_run=N)` returns a `JobClient` that resolves the
job's assignments, request caps and today's request count **once**
(snapshot per run), then sends prompts with per-model retries,
exponential backoff, throttling and provider fallback. Every attempt
sent — success or failure — is logged as an `AIRequest` row and to
the `ai_providers` logger; `client.request_count` is the attempts
sent. Caps (`AIJob.max_requests_per_run`, `max_requests_per_day` plus
the per-client argument) count attempts, not successes.

Jobs are declared in `<app>/ai_jobs.py` as `AIJobSpec` instances — a
module-level `JOB_SPECS` list and/or bare `AIJobSpec` attributes —
and seeded via `ensure_job()` on first use (default assignments are
created only once; admin edits are never overwritten). Prompts are
stored normalized (`AIPromptTemplate` + `AIInput` + `prompt_layout`);
`AIRequest.rendered_prompt()` rebuilds the exact prompt and verifies
its sha256, and the AIRequest admin detail page shows it.

Commands: `python manage.py seed_ai_config [--dry-run]` seeds the
`gemini`/`openrouter` provider presets and every discovered job spec
(idempotent); `python manage.py ai_smoke_test --job SLUG --role ROLE
[--prompt TEXT]` sends exactly one real (potentially paid) request —
use sparingly.

### PR-5: Model catalog sync

`python manage.py sync_ai_models PROVIDER_SLUG [--enable-new]
[--dry-run]` calls the provider's free model-listing endpoint via
the adapter's `list_models()` and reconciles the `ai_model` table:
unknown models are created with `auto_registered=True` (disabled
unless `--enable-new`), existing rows get catalog-provided display
name, prices and context length refreshed — nothing is ever
disabled or deleted. `ai_providers.catalog.sync_provider_models(
provider, enable_new, dry_run)` returns `{created, updated,
skipped}` counts; the same sync backs the AIProvider admin action
"Sync model catalog" (per-provider error isolation). Gemini keeps
only models supporting `generateContent` and strips the `models/`
name prefix; OpenRouter pricing strings (USD per token) are
converted to USD per 1M tokens.

### PR-6: Blogs on JobClient + PageAnalysis FKs

`blogs` no longer calls the Gemini SDK directly. `BlogScraper` builds
a `JobClient` for the `blogs.theme_analysis` spec declared in
`blogs/ai_jobs.py` (`THEME_ANALYSIS`) and hands it to
`JobClientBackend` (`blogs/ai_backends.py`), which adapts JobClient
results to the `AnalyzerBackend` protocol: `AIRequestCapReached`
re-raises as `MaxAPIRequestsReached`, `AIAllModelsFailedError` means
"every model failed, skip the theme" (`None`), and the served
`AIModel`/`AIRequest` ids ride along in `AnalyzerResponse.extra` so
`analyse_and_save_resource` can stamp the new
`PageAnalysis.ai_model`/`ai_request` FKs (null for `content_analyzer`
rows and legacy rows until PR-7 backfills).

The per-run cap now lives on the `AIJob` row
(`max_requests_per_run`, editable in admin). `blogs/config.yaml`'s
`max_api_requests` only seeds the row on first creation — afterwards
it logs a deprecation warning and is ignored. `scrape_blogs
--max-api-requests N` is a per-run override: the effective cap is the
lower of the DB value and the CLI flag.

### PR-7: Backfill `PageAnalysis.ai_model`

`python manage.py backfill_page_analysis_ai_models [--dry-run]
[--batch-size N]` (default 500) maps each distinct `model` string on
`PageAnalysis` rows with `ai_model IS NULL` to an `AIModel` under the
`gemini` provider (`auto_registered=True`), updating rows in batched
UPDATEs. `content_analyzer` rows (the media-heavy heuristic — no AI
call) keep a null FK, as does `ai_request` (no historic request data).
A missing `gemini` provider row is created from `PROVIDER_PRESETS`.
Idempotent — a re-run updates nothing.

### PR-8: Usage dashboard + retention

`/admin/ai_providers/airequest/usage/` (linked via the "Usage" object
tool on the AIRequest changelist) shows AIRequest aggregates grouped
by UTC day x job x served model — counts, errors, blocked, tokens and
cost — with a `?from=&to=` date filter (default: last 30 days), plus
a storage line with the AIInput row count and total chars. The
queries live in `ai_providers/usage.py`; the AIJob and AIModel admin
lists also carry "requests today" and "cost 30d" annotated columns.

`python manage.py prune_ai_requests --older-than-days N [--dry-run]
[--batch-size N]` deletes old AIRequest rows in batches — but only
those not referenced by any FK (consumers are discovered via
`AIRequest._meta.related_objects`, e.g. `PageAnalysis.ai_request`),
then deletes AIInput rows no longer referenced by any AIRequest.
`AIPromptTemplate` rows are never pruned.

### PR-9: Prompt hardening (system_v1 + json_mode + shape checks)

`JobClientBackend` sends prompts with layout `system_v1`: the prompt
file becomes the system message and the article arrives in the user
message wrapped in `<input>...</input>`. Every `blogs/prompts/*.txt`
file ends with a line telling the model to treat the `<input>` block
as data, not instructions (each edit creates a new
`AIPromptTemplate` version at runtime — expected). `json_mode` is
requested when any of the role's assignments has
`supports_json_mode` — the backend asks
`client.supports_json_mode(role)`, which reads the JobClient's
construction-time assignment snapshot — and `generate()` gates it
per assignment, so only flagged-capable models actually receive the
option. Parsed results are
shape-validated in `ThemeAnalyzer._parse_result`: the theme key must
be a bool, `confidence_score` a 0-1 number and `reasoning_summary` a
str — anything else is skipped like a failed parse (the synthetic
BLOCKED result is built internally and bypasses validation).

### PR-10: cv.lv public portal (nextjs) + image-vacancy OCR

`VacancyScrapper` supports a second portal config `type: 'nextjs'`
(portal `"2"` in `config_v2.json` / `FETCHER_PORTALS_JSON`): the
public `cv.lv/lv/search` pages are Next.js SSR and embed the same
vacancy objects as the API inside `<script id="__NEXT_DATA__">` —
`parse_results` reads `props.pageProps.searchResults.vacancies` and
offset-paginates via `search_params`/`page_size` in config until
`total` is covered. `enrich_result` fetches `/lv/vacancy/{id}` for
new or renewed ads only (`renewedDate` > `Vacancy.detail_fetched_at`),
merges `details.standardDetails` text into keyword matching, and
transcribes `details.fileDetails` images/PDFs (fetched from
`/api/v1/files-service/{fileId}`) through the
`fetcher.vacancy_image_ocr` AIJobSpec (`fetcher/ai_jobs.py`, role
`ocr`, prompt `fetcher/prompts/vacancy_ocr.txt`). Extracted text is
cached once per file on `VacancyFile` (`file_id` unique) — bytes
are never stored — and feeds the same `_find_keywords_in_content`
pass; it is not surfaced in the UI.

Multimodal prompts ride the normal JobClient path: `PromptSpec` /
`RenderedPrompt` carry `images: tuple[ImagePart]`; Gemini sends
inline `Part.from_bytes` parts, OpenAI-compatible sends `image_url`
data-URIs, and `AIRequest.options['images']` records each image's
sha256/mime/bytes for provenance.

## Commands

```bash
# Setup (venv at ./venv, not .venv)
source venv/bin/activate
pip install -r requirements.txt   # requirements.txt is canonical

# Verify
python manage.py check
python manage.py test <app>       # test coverage is thin; tests.py are mostly stubs

# Run
python manage.py runserver

# Scrapers (make real HTTP requests — see Guardrails)
python manage.py scrape_vacancies [portal_id]   # all configured portals by default
python manage.py scrape_apartment_ads --max-pages 10
python manage.py scrape_housing_ads
python manage.py scrape_blogs [--theme NAME] [--reanalyze] [--max-api-requests N]
python manage.py scrape_tv_programs [--force] [--dry-run]
python manage.py sync_apartment_regions / sync_housing_regions
python manage.py refetch_apartment_ads --filter "post_date__isnull=True" --dry-run
python manage.py validate_sightings
python manage.py reclassify_tv_programs
```

## Configuration

- `.env` via `django-environ`: `SECRET_KEY`, `DEBUG`, `DATABASE_URL`,
  `BASE_URL`, `HARD_CODED_PASSWORD`, `GEMINI_API_KEY`, `OMDB_KEY`,
  `ALLOWED_HOST_IP`, `DB_SSL_CERT` (or `capem`).
- DB: `DATABASE_URL=sqlite:///db.sqlite3` locally; PostgreSQL in prod
  (SSL CA written to `/tmp/industry-analyser-postgres-ca.pem` from
  `DB_SSL_CERT` env or `ca.pem` file fallback).
- Fetcher portals config: `FETCHER_PORTALS_JSON` env (prod, from Secret
  Manager) or `fetcher/config_v2.json` (local). On Cloud Run,
  `scripts/materialize_fetcher_config_and_scrape.py` materializes
  `config_v2.json` from `FETCHER_PORTALS_JSON` +
  `FETCHER_KEYWORDS_LIST_JSON` then runs the scraper.
- `blogs/config.yaml` holds listing URLs and per-URL
  `use_cheap_tier`; its legacy `max_api_requests` key only seeds the
  `AIJob` row once (the live cap is `AIJob.max_requests_per_run`).

## Conventions

- Max line length **79 chars** (`.flake8`, migrations excluded).
  Match the existing style: compact functions, double-quoted strings
  mixed with single, `logging.getLogger('<app_name>')` per app (loggers
  are pre-configured in settings for each app name — use them, not
  `__name__`, so file logging works).
- Models use explicit `db_table` names and `unique_together`; abstract
  bases (`BaseApartmentAd`, `BaseHouseAd`) back the concrete rent/sale
  models.
- Views are function-based; URLs live in each app's `urls.py` with an
  `app_name` namespace.

## Deployment

Push to `master` triggers GitHub Actions
(`.github/workflows/deploy-scraper-jobs.yml` and
`deploy-web-service.yml`): Terraform apply → Docker build/push to
Artifact Registry → update Cloud Run jobs + web service. Legacy
`cloudbuild.yaml`, `deploy-cloudrun.sh`, and `vercel.json` also exist.
Don't hand-edit Terraform-managed resources; change `terraform/*.tf`
and let CI apply.

## Guardrails

- **Never run migrations** (`migrate`/`makemigrations`) — ask the user.
- **Never commit** `.env`, `ca.pem`, `private_settings.json`,
  `db.sqlite3`, `fetcher/config_v2.json`, `blogs/config.yaml`,
  `terraform/*.tfvars`/`tfstate` — all gitignored local state/secrets.
- Scraper commands hit live sites and (for `blogs`) paid APIs. Prefer
  `--dry-run`/`--max-pages`/small `--limit` when testing; don't run
  full scrapes just to verify a code change.
- `scripts/fix_apartment_addresses.py` and similar modify real data —
  treat as one-off fix scripts, don't run casually.

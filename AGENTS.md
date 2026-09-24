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
- **AI cost control**: `blogs` uses two Gemini model tiers
  (`cheap`/`expensive`) and a `max_api_requests` cap in
  `blogs/config.yaml`. Respect the cap; API calls cost money.

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
python manage.py scrape_first_vacancy_portal [portal_id]   # positional arg, default 1
python manage.py scrape_apartment_ads --max-pages 10
python manage.py scrape_housing_ads
python manage.py scrape_blogs [--theme NAME] [--reanalyze]
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
- `blogs/config.yaml` holds listing URLs, `max_api_requests`, and
  per-URL `use_cheap_tier`.

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

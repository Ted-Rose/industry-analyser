# Fetcher App - Vacancy Scraper

The `fetcher` app scrapes job vacancy data from various job portals and stores
it in the database for analysis.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Configuration](#configuration)
- [Local Development](#local-development)
- [Production Deployment](#production-deployment)
- [Portal Configuration](#portal-configuration)
- [How It Works](#how-it-works)
- [Troubleshooting](#troubleshooting)

## Architecture Overview

The fetcher app uses a class-based scraper architecture:

```
core_scraper/base.py (BaseScraper)
    ↓
fetcher/scraper.py (VacancyScrapper)
    ↓
Django Management Command
    ↓
Cloud Run Job (production) or Local CLI (development)
```

### Key Components

- **`BaseScraper`** (`core_scraper/base.py`): Abstract base class providing
  common scraping functionality (HTTP requests, retry logic, rate limiting)
- **`VacancyScrapper`** (`fetcher/scraper.py`): Implements vacancy-specific
  scraping logic for multiple portals
- **`scrape_vacancies`**: Django management command to run the scraper
  (all configured portals by default, or a single `portal_id`)
- **`materialize_fetcher_config_and_scrape.py`**: Production script that
  builds config from environment variables and runs the scraper

## Configuration

### Configuration Sources

The scraper uses **different configuration sources** depending on the
environment:

| Environment | Config Source | Location |
|-------------|---------------|----------|
| **Local Development** | File | `fetcher/config_v2.json` (gitignored) |
| **Production (Cloud Run)** | Environment Variable | `FETCHER_PORTALS_JSON` from GCP Secret Manager |

### Configuration Loading Logic

```python
# In VacancyScrapper.__init__()
portals_json = os.environ.get('FETCHER_PORTALS_JSON')
if portals_json:
    # Production: Use environment variable
    portals = json.loads(portals_json)
else:
    # Local: Fall back to config_v2.json
    with open('fetcher/config_v2.json', 'r') as file:
        config = json.load(file)
        portals = config['portals']
```

### Configuration Schema

```json
{
  "keywords_list": ["keyword1", "keyword2"],
  "portals": {
    "1": {
      "id": "1",
      "order": 2,
      "type": "api",
      "base_url": "https://www.cv.lv",
      "search_href": "/api/v1/vacancy-search-service/search",
      "search_params": "categories%5B0%5D=INFORMATION_TECHNOLOGY",
      "page_size": 1000,
      "vacancy_base_url": "https://www.cv.lv",
      "vacancy_base_href": "/lv/vacancy/",
      "industry_mapping": {
        "1": "1",
        "10": "it"
      }
    },
    "2": {
      "id": "2",
      "order": 1,
      "type": "nextjs",
      "base_url": "https://www.cv.lv",
      "search_href": "/lv/search",
      "search_params": "categories%5B0%5D=INFORMATION_TECHNOLOGY",
      "page_size": 100,
      "vacancy_base_url": "https://www.cv.lv",
      "vacancy_base_href": "/lv/vacancy/",
      "files_href": "/api/v1/files-service/",
      "industry_mapping": {
        "1": "1",
        "10": "it"
      }
    }
  }
}
```

#### Portal Configuration Fields

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| `id` | Yes | Portal identifier | `"1"` |
| `order` | No | Run order across portals (default: numeric key) | `1` |
| `type` | No | `"api"` (JSON) or `"nextjs"` (SSR public pages) | `"api"` |
| `base_url` | Yes | Base URL for the portal | `"https://www.cv.lv"` |
| `search_href` | Yes | Search endpoint path | `"/api/v1/vacancy-search-service/search"` |
| `search_params` | Yes* | Query string appended to every search page (e.g. a `categories[]` filter) | `"categories%5B0%5D=INFORMATION_TECHNOLOGY"` |
| `page_size` | No | `limit` per search page (default `1000`) | `100` |
| `vacancy_base_url` | Yes | Base URL for vacancy detail pages | `"https://www.cv.lv"` |
| `vacancy_base_href` | Yes | Path prefix for vacancy URLs | `"/lv/vacancy/"` |
| `files_href` | nextjs only | files-service path for vacancy attachments (OCR) | `"/api/v1/files-service/"` |
| `industry_mapping` | No | Portal category id → local `Industry.name` | `{"10": "it"}` |

\* An API portal without `search_params` falls back to the legacy
per-keyword search loop (`?limit=1000&keywords[]=<keyword>` for every
`Keyword` with `only_filter=False`).

**Important**: The `type` field controls scraping behavior:
- `"api"`: JSON API scraping (no detail-page enrichment)
- `"nextjs"`: server-rendered Next.js pages — the same vacancy objects
  come embedded in `__NEXT_DATA__`, plus detail pages are fetched for
  new/renewed ads (`standardDetails` text + OCR of attached files)

## Local Development

### Setup

1. **Activate virtual environment**:
   ```bash
   source venv/bin/activate
   ```

2. **Create local config** (if not exists):
   ```bash
   # config_v2.json is gitignored, so you need to create it
   # See Configuration Schema above for structure
   ```

3. **Ensure database is set up**:
   ```bash
   python manage.py migrate
   ```

### Running the Scraper Locally

**Basic usage** (scrapes all configured portals):
```bash
python manage.py scrape_vacancies
```

**With specific portal ID**:
```bash
python manage.py scrape_vacancies 1
```

### Testing Without Writes

The search sweep is one or two requests regardless of keyword count —
keywords are applied locally to the returned vacancy content, not sent
as search queries. To test safely:

```bash
# Fetch and parse but write nothing
python manage.py scrape_vacancies --dry-run

# Or a single portal only
python manage.py scrape_vacancies 1 --dry-run
```

### Local Configuration File

The local `config_v2.json` is **gitignored** to prevent accidental commits of
sensitive or environment-specific data. Each developer maintains their own
copy.

**Location**: `fetcher/config_v2.json`

**Example structure**: See Configuration Schema above.

## Production Deployment

### Cloud Run Job Architecture

The scraper runs as a **Cloud Run Job** (not a service) triggered by Cloud
Scheduler:

```
Cloud Scheduler (cron: "0 2 * * 1" — weekly, Mon 02:00 UTC)
    ↓ HTTP POST
Cloud Run Job: scrape-vacancy
    ↓ runs
scripts/materialize_fetcher_config_and_scrape.py
    ↓ builds config from env vars
    ↓ runs
python manage.py scrape_vacancies <portal_id>
```

### Configuration Management

**GCP Secret Manager** stores the portal configuration:

- **Secret Name**: `industry-analyser-fetcher-portals`
- **Project**: `gen-lang-client-0833674612`
- **Region**: `europe-north1`

The secret contains **only the `portals` object** (not the full config):

```json
{
  "1": {
    "id": "1",
    "type": "api",
    ...
  },
  "2": { ... },
  "3": { ... }
}
```

### Environment Variables (Cloud Run)

The Cloud Run job receives these environment variables:

| Variable | Source | Description |
|----------|--------|-------------|
| `FETCHER_PORTALS_JSON` | GCP Secret Manager | Portal configurations (JSON string) |
| `FETCHER_KEYWORDS_LIST_JSON` | GCP Secret Manager (optional) | Keywords list override |
| `DATABASE_URL` | Secret | PostgreSQL connection string |
| `SECRET_KEY` | Secret | Django secret key |
| Other Django settings | Secrets | Various Django configuration |

### Updating Production Configuration

**Method 1: Using gcloud CLI**

```bash
# 1. Prepare the updated JSON (portals object only)
cat > /tmp/portals.json << 'EOF'
{
  "1": {
    "id": "1",
    "type": "api",
    "base_url": "https://www.cv.lv",
    ...
  }
}
EOF

# 2. Set the correct project
gcloud config set project gen-lang-client-0833674612

# 3. Create a new secret version
gcloud secrets versions add industry-analyser-fetcher-portals \
  --data-file=/tmp/portals.json

# 4. Verify
gcloud secrets versions access latest \
  --secret="industry-analyser-fetcher-portals"
```

**Method 2: Using GCP Console**

1. Navigate to Secret Manager in GCP Console
2. Find `industry-analyser-fetcher-portals`
3. Click "New Version"
4. Paste the JSON content
5. Save

### Deployment Status

**Current Status** (as of 2026-08-25):

- ✅ Secret updated with corrected cv.lv API configuration
- ⚠️ Cloud Run job is **DISABLED** (commented out in `terraform/main.tf`)
- ⚠️ Cloud Scheduler is **DISABLED** (commented out in `terraform/main.tf`)

**To re-enable production scraping**:

1. Edit `terraform/main.tf`
2. Uncomment the `google_cloud_run_v2_job.scrape_vacancy` resource
3. Uncomment the `google_cloud_scheduler_job.scrape_vacancy` resource
4. Run `terraform apply`

### Terraform Resources

**Job Definition** (currently disabled):
```hcl
# resource "google_cloud_run_v2_job" "scrape_vacancy" {
#   name     = "scrape-vacancy"
#   location = var.region
#   ...
# }
```

**Scheduler** (currently disabled):
```hcl
# resource "google_cloud_scheduler_job" "scrape_vacancy" {
#   name      = "scrape-vacancy-trigger"
#   schedule  = "0 2 * * *"  # Daily at 2 AM UTC
#   ...
# }
```

## Portal Configuration

### Supported Portals

| Portal ID | Name | Type | Status |
|-----------|------|------|--------|
| 2 | cv.lv (public site) | Next.js SSR (`__NEXT_DATA__`) | ✅ Working — detail enrichment + file OCR |
| 1 | cv.lv (API) | JSON API category sweep | ✅ Working — discovery + sightings |

Both portals read the same cv.lv vacancy namespace and the same
`search_params` IT-category sweep. The public portal runs first
(`order: 1`) and detail-fetches new/renewed ads; the API portal
(`order: 2`) then bumps `last_seen` on everything it sees and creates
rows for anything the public pages missed.

### Portal 1: cv.lv API

**Type**: JSON API
**Endpoint**: `https://www.cv.lv/api/v1/vacancy-search-service/search`
**Documentation**: https://www.cv.lv/api/doc/swagger-ui/index.html

**Configuration**:
```json
{
  "id": "1",
  "order": 2,
  "type": "api",
  "base_url": "https://www.cv.lv",
  "search_href": "/api/v1/vacancy-search-service/search",
  "search_params": "categories%5B0%5D=INFORMATION_TECHNOLOGY",
  "vacancy_base_url": "https://www.cv.lv",
  "vacancy_base_href": "/lv/vacancy/",
  "industry_mapping": { "10": "it" }
}
```

The search response carries the full `positionContent` for every
vacancy — the `categories[]` filter replaces the old per-keyword
search loop (~108 requests → 1–2 per run). Keywords still tag rows
via local content matching.

**API Response Structure**:
```json
{
  "vacancies": [
    {
      "id": 1645116,
      "positionTitle": "Job Title",
      "employerName": "Company Name",
      "salaryFrom": 1000.0,
      "salaryTo": 2000.0,
      "publishDate": "2026-08-25T06:38:12.000+00:00",
      "expirationDate": "2026-09-24T23:59:59.999+00:00",
      "categories": [5, 6, 20],
      "keywords": []
    }
  ],
  "workTimes": { ... },
  "categories": { ... }
}
```

### Portal 2: cv.lv public site (Next.js)

**Type**: `nextjs` — server-rendered `/lv/search` and
`/lv/vacancy/{id}` pages embed the vacancy objects as JSON inside
`<script id="__NEXT_DATA__">`.

This is the enrichment portal: detail pages are fetched only for new
or renewed ads (`renewedDate` > `detail_fetched_at`), adding
`standardDetails` text and OCR transcription of attached image/PDF
files (`VacancyFile`, via the `fetcher.vacancy_ocr` AI job).

## How It Works

### Scraping Flow

```
1. get_search_urls()
   ↓ Offset-paginates search_params (e.g. an IT-category sweep)
   ↓ until offset >= total — one checkpoint item per portal
   
2. scrape_portal(url)
   ↓ Makes HTTP request
   
3. parse_results(response)
   ↓ Parses __NEXT_DATA__ (nextjs) or JSON body (api)
   ↓ Stores `total` for pagination
   
4. remove_redundant_results(results)
   ↓ Drops vacancy ids already seen this run
   
5. initiate_resources(results)
   ↓ Creates unsaved Vacancy instances
   ↓ Parses datetime fields
   ↓ Stores pending M2M relationships
   
6. create_or_update_resources(vacancies)
   ↓ bulk_create new rows
   ↓ one bulk last_seen UPDATE for unchanged sightings
   ↓ bulk_update for rows that actually changed
   ↓ bulk INSERT of M2M through rows (ignore_conflicts)
```

### API vs Next.js Scraping

The scraper supports two modes controlled by the `enrich_search_results` flag:

**API Mode** (`type: "api"` in config):
- `enrich_search_results = False`
- Parses the JSON response directly — `positionContent` is complete
- No additional HTTP requests per vacancy
- Faster, more reliable

**Next.js Mode** (`type: "nextjs"`):
- `enrich_search_results = True`
- Parses `__NEXT_DATA__` from SSR search pages (same vacancy objects)
- Fetches the public detail page for new/renewed ads only
- Detail adds `standardDetails` text and OCR of attached files

### Keyword Matching

The scraper uses a **two-step keyword matching** approach:

1. **Portal Keywords**: Uses keywords explicitly provided by the API
   ```python
   portal_keywords = result.get('keywords')
   ```

2. **Content Scanning**: Searches for keywords in vacancy content
   ```python
   content = title + description + company_name
   matched_keywords = regex_search(content, all_keywords)
   ```

This ensures vacancies are tagged even if the portal doesn't provide explicit
keyword metadata.

### Database Operations

**Create or Update Logic**:
```python
# Materialize existing rows once, keyed by vacancy_portal_id
existing = {v.vacancy_portal_id: v for v in Vacancy.objects.filter(
    vacancy_portal_id__in=scraped_ids)}

# New rows: one bulk_create
# Sightings (no field changes): one bulk last_seen UPDATE
# Changed rows (filled-in fields, fresh detail fetch): bulk_update
```

**M2M Relationships**:
- Industries: `categories` ids mapped through `industry_mapping`
  (e.g. `"10"` → `"it"`); unmapped ids fall back to a numeric-name
  `Industry` lookup
- Keywords: Combined from portal keywords + content scan
- Both are written as through-model rows (`VacancyIndustries`,
  `VacancyContainsKeyword`) via `bulk_create(ignore_conflicts=True)`
  — two INSERTs per page instead of per-vacancy `.add()` calls

### Date/Time Handling

**API dates** are ISO 8601 strings with timezone:
```python
from django.utils.dateparse import parse_datetime

first_seen = parse_datetime(result.get('publishDate'))
# "2026-08-25T06:38:12.000+00:00" → datetime object
```

**Local timestamps** use Django's timezone-aware `now()`:
```python
from django.utils import timezone

last_seen = timezone.now()
```

## Troubleshooting

### Common Issues

#### 1. "No results found" for API portal

**Symptom**: Scraper completes but finds 0 vacancies

**Possible Causes**:
- Incorrect API endpoint URL
- Content-Type header check failing
- API response structure changed

**Debug**:
```bash
# Test the API directly
curl -v "https://www.cv.lv/api/v1/vacancy-search-service/search?limit=1&keywords=python"

# Check Content-Type header
# Should be: Content-Type: application/json
```

#### 2. IntegrityError: duplicate key value

**Symptom**: `IntegrityError` on `vacancy_portal_id`

**Cause**: Double-write bug (fixed as of 2026-08-25)

**Solution**: Ensure you're using the latest version of `scraper.py` where
`initiate_resources()` creates unsaved instances

#### 3. TypeError: expected string or bytes-like object

**Symptom**: Error when saving datetime fields

**Cause**: Missing datetime parsing (fixed as of 2026-08-25)

**Solution**: Ensure `parse_datetime()` is used for date fields

#### 4. Configuration not loading in production

**Symptom**: Scraper uses old config despite updating secret

**Debug**:
```bash
# Check the secret version
gcloud secrets versions list industry-analyser-fetcher-portals

# Verify the latest version content
gcloud secrets versions access latest \
  --secret="industry-analyser-fetcher-portals"

# Check Cloud Run job environment
gcloud run jobs describe scrape-vacancy --region=europe-north1
```

**Solution**: Ensure the Cloud Run job has permission to access the secret
(IAM role: `roles/secretmanager.secretAccessor`)

#### 5. Scraper times out

**Symptom**: Cloud Run job exceeds timeout

**Possible Causes**:
- Portal is slow or rate-limiting (detail-page enrichment and file
  OCR are the slow paths, not the 1–2 search requests)
- Network issues

**Solutions**:
- Increase Cloud Run job timeout (currently 8000s)
- Reduce number of active keywords
- Add retry logic with exponential backoff

### Debugging Tips

**Enable debug logging**:
```python
import logging
logging.getLogger('fetcher').setLevel(logging.DEBUG)
```

**Fetch without writing**:
```bash
python manage.py scrape_vacancies --dry-run
```

**Inspect raw API response**:
```python
response = scraper.make_request(url)
print(response.data.decode('utf-8'))
```

**Check database state**:
```python
from fetcher.models import Vacancy

# Recent vacancies
recent = Vacancy.objects.order_by('-last_seen')[:10]

# Duplicates check
from django.db.models import Count
dupes = Vacancy.objects.values('vacancy_portal_id').annotate(
    count=Count('id')
).filter(count__gt=1)
```

## Development History

### Recent Changes (2026-08-25)

**Fixed cv.lv API Integration**:
- Updated API endpoint from broken URL to correct endpoint
- Fixed Content-Type header check (`==` → `in`)
- Added `type: "api"` flag to disable HTML enrichment
- Fixed double-write bug in `initiate_resources()`
- Added datetime parsing for `publishDate` and `expirationDate`
- Moved `enrich_search_results` flag to `__init__()`
- Updated GCP Secret Manager with corrected config

**Testing Results**:
- ✅ Successfully scraped 33 vacancies from cv.lv API
- ✅ No duplicates on second run
- ✅ `last_seen` timestamps updated correctly
- ✅ All fields populated (title, company, salary, dates, URL)
- ✅ Keywords extracted from content

### Known Issues

- Cloud Run job is disabled in production (needs Terraform re-enable)

## Related Documentation

- [cv.lv API Swagger Docs](https://www.cv.lv/api/doc/swagger-ui/index.html)
- [Task Document](../docs/cvlv_api_integration_task.md)
- [Core Scraper Base Class](../core_scraper/base.py)
- [Terraform Configuration](../terraform/main.tf)

## Support

For issues or questions:
1. Check this README first
2. Review the task document in `docs/cvlv_api_integration_task.md`
3. Check recent git commits for context
4. Test locally before deploying to production

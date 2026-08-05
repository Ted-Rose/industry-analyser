# Housing Scraper Setup Summary

## Overview
Added support for scraping housing ads (homes/summer residences) from ss.com, separate from the existing apartment scraper.

## Changes Made

### 1. Fixed Housing Scraper Implementation
**File:** `classified_ads/housing_scraper.py`

**Issue:** The scraper was checking for 9 columns (like apartments) but housing ads have only 8 columns.

**Fix:**
- Changed column count check from `len(cells) != 9` to `len(cells) != 8`
- Adjusted column indices to match the 8-column structure:
  - [0]: Empty (checkbox)
  - [1]: Empty (icon/image)
  - [2]: Comment/Description
  - [3]: City/Street
  - [4]: Area (m²)
  - [5]: Floors
  - [6]: Land area
  - [7]: Price
- Removed rooms parsing logic (housing ads don't have a rooms column)
- Set `rooms: 0` for all housing ads

### 2. Created Housing Regions Sync Command
**File:** `classified_ads/management/commands/sync_housing_regions.py`

A new Django management command that:
- Fetches housing regions from ss.com (`/real-estate/homes-summer-residences/`)
- Syncs them to the `classified_ads_region` table
- Enables sub-regions for scraping by default
- Successfully synced 493 housing regions (463 enabled)

### 3. Applied Database Migrations
Ran pending migrations to create the housing tables:
- `classified_ads.0011_houseforsale_houseforsalesighting_and_more`
- `classified_ads.0012_houseforrent_houseforrentsighting`

### 4. Added Terraform Infrastructure

#### Cloud Run Job: `sync-housing-regions`
**File:** `terraform/main.tf`

```hcl
resource "google_cloud_run_v2_job" "sync_housing_regions"
```

- **Command:** `python manage.py sync_housing_regions`
- **Resources:** 1 CPU, 512Mi memory
- **Timeout:** 30 minutes (1800s)
- **Schedule:** Weekly on Sundays at 01:30 UTC (30 minutes after apartment regions sync)

#### Cloud Scheduler
**File:** `terraform/main.tf`

```hcl
resource "google_cloud_scheduler_job" "trigger_sync_housing_regions"
```

- **Schedule:** `30 1 * * 0` (Sundays at 01:30 UTC)
- **Description:** Sync ss.com housing regions to DB weekly

#### IAM Permissions
**File:** `terraform/main.tf`

```hcl
resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_sync_housing_regions"
```

Grants the scheduler service account permission to invoke the job.

#### Monitoring Alert
**File:** `terraform/monitoring.tf`

```hcl
resource "google_monitoring_alert_policy" "sync_housing_regions_failure"
```

- Monitors job failures (application errors, OOM, timeouts, etc.)
- Sends email notifications via the configured alert channel
- Auto-closes after 24 hours
- Rate-limited to prevent spam (max 1 notification per 5 minutes)

#### Outputs
**File:** `terraform/outputs.tf`

Added `sync_housing_regions_failure` alert policy to the outputs.

## Database Structure

### Tables
- **`classified_ads_region`** - Stores both apartment and housing regions
  - Distinguished by URL pattern:
    - Apartments: `/real-estate/flats/`
    - Housing: `/real-estate/homes-summer-residences/`
  - Total: 910 regions (417 apartments + 493 housing)

- **`classified_ads_houseforrent`** - Housing rental listings
- **`classified_ads_houseforsale`** - Housing sale listings
- **`classified_ads_houseforrentsighting`** - Rental sightings (for tracking)
- **`classified_ads_houseforsalesighting`** - Sale sightings (for tracking)

## Manual Commands

### Sync Housing Regions (one-time or manual)
```bash
python manage.py sync_housing_regions
```

### Scrape Housing Ads
```bash
python manage.py scrape_housing_ads --max-pages=10
```

## Verification

Tested successfully with Jurmala region:
- ✅ Scraped 120 housing ads (60 for rent, 60 for sale)
- ✅ Data properly saved with all fields populated
- ✅ Both rent and sale listings processed across multiple pages

## Deployment

To deploy the new infrastructure:

```bash
cd terraform
terraform plan
terraform apply
```

This will create:
1. Cloud Run job: `sync-housing-regions`
2. Cloud Scheduler job: `trigger-sync-housing-regions`
3. IAM binding for scheduler invoker
4. Monitoring alert policy for job failures

## Monitoring

After deployment, you can monitor the job at:
- **Cloud Run Console:** https://console.cloud.google.com/run/jobs/details/[REGION]/sync-housing-regions?project=[PROJECT_ID]
- **Cloud Scheduler Console:** https://console.cloud.google.com/cloudscheduler?project=[PROJECT_ID]
- **Monitoring Alerts:** https://console.cloud.google.com/monitoring/alerting?project=[PROJECT_ID]

## Notes

- The housing regions sync runs 30 minutes after the apartment regions sync to avoid conflicts
- Both scrapers share the same `Region` model but target different URL patterns
- Housing ads don't have a "rooms" field, so it's always set to 0
- The scraper uses the same base infrastructure (service accounts, secrets, etc.) as other scrapers

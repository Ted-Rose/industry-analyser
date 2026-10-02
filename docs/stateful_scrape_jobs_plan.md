# Stateful Scrape-Job Execution & Checkpointing Plan

> **Audience**: AI agents / developers implementing this.
> Read sections 1–4 once (shared spec), then implement the PR cards
> in section 7, following the guardrails in section 8.
>
> Adapted from a generic "stateful job execution" prompt. Where the
> generic version conflicted with this codebase, the delta is noted
> in section 3.

## 1. Objective

Make every long-running scraper resumable. When a run is interrupted
(laptop lid closed, `gcloud run jobs executions cancel`, Cloud Run
timeout, OOM), the next run — on the same machine or as the
scheduled Cloud Run job — continues from the checkpoint instead of
restarting. State lives in the database, so local runs and Cloud Run
job executions share progress **as long as they share the same
`DATABASE_URL`** (see caveat in section 3.6).

## 2. Current state (verified)

### 2.1 What already exists

- `classified_ads` scrapers **already resume** — but implicitly, via
  sighting rows. `ApartmentAdScraper._get_last_scraped_region_id()`
  and the identical copy in `HousingAdScraper` find the region of the
  newest `*Sighting` row in a lookback window (1 day locally, 6 days
  on GCP — GCP detected via `K_SERVICE`/`K_REVISION`/
  `GOOGLE_CLOUD_PROJECT`), then `get_search_urls()` re-starts at that
  region. Fragile: a region whose pages yielded zero ads leaves no
  sighting, so the resume point can be wrong; there is no run-level
  status, error capture, or heartbeat.
- `BaseScraper.run()` iterates `get_search_urls()` (a generator) →
  `scrape_portal()` per URL. Scrapers track position in ad-hoc
  attributes (`self._current_region`, `_current_deal_type`,
  `current_channel`, `current_start_time`).
- `core_scraper` is a plain package, **not** in `INSTALLED_APPS` —
  models cannot live there without promoting it (see ADR-2 in
  `docs/ai_provider_abstraction_plan.md`).
- `ai_providers` is the precedent for a cross-cutting feature app:
  DB tables + `AIJobSpec` declarations in `<app>/ai_jobs.py` +
  `ensure_job()` seeding that never overwrites admin edits. Reuse
  this pattern.
- Naming hazard: `ai_providers.AIJob` already exists (`ai_job`
  table), and "job" in this codebase also means a *job vacancy*
  (`fetcher.Vacancy`). Do not introduce bare `Job`/`JobItem` models —
  prefix with `Scrape`.

### 2.2 Iteration units per command

| Command | Item unit | Source of items | Order today |
|---|---|---|---|
| `scrape_apartment_ads` | `Region` × deal type (`hand_over/`=RENT, `sell/`=SELL) | `Region.objects.filter(scrape_enabled=True)` | `order_by('id')` |
| `scrape_housing_ads` | `Region` × deal type, only urls containing `/homes-summer-residences/` | same queryset + URL filter | `order_by('id')` |
| `scrape_vacancies [portal_id]` | `Keyword` (one URL each, `?limit=1000&keywords[]=`) | `Keyword.objects.filter(only_filter=False)` | unordered (PK) |
| `scrape_blogs` | Listing URL (each paginates via `<link rel="next">`) | `blogs/config.yaml` `blog_listing_urls` | yaml order |
| `scrape_tv_programs` | Channel × date (~3 channels × 14 days) | hardcoded `self.channels` dict | chronological |

`Region.order_id` (CharField, default `'1'`) exists but is **unused**
— candidate seed value for item priority.

### 2.3 Infra facts

- Cloud Run jobs live in `europe-north1`; Cloud Scheduler in
  `europe-west1`. `terraform/main.tf` job blocks are currently
  commented out but the jobs may still exist in GCP (`prevent_destroy`
  + `update_job_if_exists` in `deploy-scraper-jobs.yml`):
  `scrape-vacancy`, `scrape-tv-programs`, `scrape-apartment-ads`,
  `scrape-housing-ads`, `sync-apartment-regions`, `sync-housing-regions`.
- Job timeouts: 8000s for scrapers, 1800s for region syncs;
  `task_count = 1`; `max_retries` 0 or 1.
- Cloud Run Jobs env vars: `CLOUD_RUN_JOB`, `CLOUD_RUN_EXECUTION`,
  `CLOUD_RUN_TASK_INDEX`, `CLOUD_RUN_TASK_ATTEMPT` (plus `K_SERVICE`,
  `K_REVISION` as on services).
- DB: SQLite locally (`db.sqlite3`), PostgreSQL in prod.
  `run-migrations.yml` applies migrations in CI only when
  `migrations/` changed in `HEAD~1..HEAD` → PRs containing migrations
  must be squash-merged or the workflow triggered manually.

## 3. Design decisions (deltas from the generic plan)

1. **New app `scrape_jobs`** in `INSTALLED_APPS` — holds the three
   models, admin, and the runner service. Mirrors the `ai_providers`
   precedent. `core_scraper` stays a plain package.
2. **Cycle-scoped resume.** The generic plan resumes from "the most
   recent checkpoint" forever — wrong for periodic scrapes (a
   SUCCESS run yesterday must not suppress today's pass). Introduce
   `cycle_key` (CharField, default = UTC `date.isoformat()`, matching
   the sightings-per-day invariant; overridable with `--cycle`).
   Resume rule: skip the union of items completed by **all** runs in
   the cycle (not just the last run's tail — covers
   chain-of-failures), including after a SUCCESS run — a finished
   pass is not silently repeated.
   `--fresh` forces a full pass regardless.
   Commands may pick a coarser default key: the vacancy scraper runs
   weekly, so `scrape_vacancies` defaults to the ISO week
   (`YYYY-Www`, `iso_week_cycle_key()`).
3. **Per-item completion records**, not just `last_completed_item`.
   Priority ordering makes position-based resume work only while
   priorities are stable; a `ScrapeJobRunItem` join table (or a
   completed-keys JSONField — pick the table, it is queryable in
   admin) makes skip-set computation trivial and survives
   mid-cycle priority edits. Keep `last_completed_item` FK on the
   run as a human-readable convenience.
4. **Heartbeat.** `updated_at` is touched at every item checkpoint
   *and* between pages inside an item (`run.touch()` — one cheap
   `UPDATE`), because a single region can paginate for many minutes
   and a flat 30-min staleness rule could false-positive. Stale
   threshold is `ScrapeJob.stale_timeout_minutes` (default 30).
5. **Item model.** `ScrapeJobItem` keyed by `(job, key)` — a string
   the scraper defines (`"42"` region PK, `"python"` keyword name,
   `"https://…/lp/l1/"` listing URL). Do **not** duplicate
   `Region.scrape_enabled`/`Keyword.only_filter` semantics: the
   source queryset still decides membership; item sync upserts
   key/label/priority on first sight and never overwrites admin
   edits — `ScrapeJobItem.is_active` is an extra kill-switch on top
   (item skipped when either side disables it).
6. **Item failure isolation + per-item email alert.** A failing
   item must not abort the run: it is recorded `FAILED`, an alert
   email is sent for *that item*, and iteration continues. A run
   that finished with ≥1 failed item ends `PARTIAL`, not `FAILED`.
   Alert transport reuses the existing channel — Cloud Monitoring
   email notification channel in `terraform/monitoring.tf`
   (`industry-analyser-alert-email` secret) — via a **log-based
   alert policy** (`condition_matched_log`) keyed on a structured
   `SCRAPE_ITEM_FAILED` marker emitted by `item_failed()`. The
   existing `*_failure` alert policies (whole-execution failures)
   stay as-is; item alerts are additive. No Django SMTP exists and
   none is added — local runs only write the marker to the log.
7. **Shared-DB caveat.** Cross-environment resume only works when
   local and Cloud Run point at the same `DATABASE_URL` (prod
   Postgres). With the default local `sqlite:///db.sqlite3`, each
   side checkpoints independently — which is still useful locally.
8. **Command to cancel a Cloud Run execution is
   `gcloud run jobs executions cancel`** — the generic plan's
   `stop` subcommand does not exist.

## 4. Data model (`scrape_jobs/models.py`)

```python
class ScrapeJob(models.Model):
    slug = models.CharField(max_length=100, unique=True)
        # e.g. 'classified_ads.apartment_ads', 'fetcher.vacancies.1'
    description = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=True)
    stale_timeout_minutes = models.PositiveIntegerField(default=30)
    created_at / updated_at

    class Meta:
        db_table = 'scrape_job'


class ScrapeJobItem(models.Model):
    job = FK(ScrapeJob, related_name='items', on_delete=CASCADE)
    key = models.CharField(max_length=500)     # scraper-defined
    label = models.CharField(max_length=255, blank=True)
    priority = models.IntegerField(default=0)  # higher runs first
    is_active = models.BooleanField(default=True)
    created_at / updated_at

    class Meta:
        db_table = 'scrape_job_item'
        unique_together = ('job', 'key')
        ordering = ['-priority', 'id']


class ScrapeJobRun(models.Model):
    STATUS = ['RUNNING', 'SUCCESS', 'FAILED', 'ABANDONED', 'PARTIAL']

    job = FK(ScrapeJob, related_name='runs', on_delete=CASCADE)
    cycle_key = models.CharField(max_length=50, db_index=True)
    execution_id = models.CharField(max_length=200, db_index=True)
    executed_by = models.CharField(max_length=20)
        # 'local' | 'gcp_cloud_run'
    status = models.CharField(max_length=20, choices=...)
    last_completed_item = FK(ScrapeJobItem, null=True, SET_NULL)
    error_message = models.TextField(blank=True)
    started_at = auto_now_add; updated_at = auto_now (heartbeat)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'scrape_job_run'
        indexes = [models.Index(fields=['job', 'cycle_key'])]


class ScrapeJobRunItem(models.Model):
    run = FK(ScrapeJobRun, related_name='items', on_delete=CASCADE)
    item = FK(ScrapeJobItem, on_delete=CASCADE)
    status = ['DONE', 'FAILED', 'SKIPPED']
    error_message = models.TextField(blank=True)
    completed_at = auto_now_add

    class Meta:
        db_table = 'scrape_job_run_item'
        unique_together = ('run', 'item')
```

## 5. Runner service (`scrape_jobs/runner.py`)

```python
class ScrapeJobRunner:
    """One instance per command invocation."""

    def __init__(self, slug, cycle_key=None, fresh=False):
        # ensure_job(slug) → ScrapeJob row (get_or_create)
        # stale-sweep: same job, status=RUNNING,
        #   updated_at < now - stale_timeout_minutes → ABANDONED
        # completed_keys = keys of DONE ScrapeJobRunItems across
        #   this job's runs in this cycle (empty if --fresh)
        # create ScrapeJobRun(status='RUNNING', execution_id=…,
        #   executed_by=…, cycle_key=…)

    def pending_items(self, items): ...
        # items: iterable of ScrapeJobItem created/synced by caller;
        # returns those ordered by (-priority, id) minus
        # completed_keys minus inactive

    def item_done(self, item): ...
        # ScrapeJobRunItem(DONE) + last_completed_item + touch()

    def item_failed(self, item, exc): ...
        # ScrapeJobRunItem(FAILED) + error_message + touch()
        # + logger.error with 'SCRAPE_ITEM_FAILED' marker →
        #   log-based alert policy emails the item failure;
        #   the caller then continues with the next item

    def touch(self): ...                    # heartbeat UPDATE
    def finish(self, status='SUCCESS', error=''): ...
        # sets completed_at
```

Execution-id / environment detection (shared helper):

```python
executed_by = (
    'gcp_cloud_run' if os.getenv('K_SERVICE')
    or os.getenv('K_REVISION')
    or os.getenv('GOOGLE_CLOUD_PROJECT') else 'local'
)
execution_id = (
    os.getenv('CLOUD_RUN_EXECUTION')
    + f"-{os.getenv('CLOUD_RUN_TASK_INDEX', '0')}"
    or f"local-{socket.gethostname()}-{os.getpid()}"
)
```

### 5.1 Integration pattern (minimal diff)

`BaseScraper.run()` is **not** modified. Each scraper's
`get_search_urls()` already owns the item loop; wire the runner in
at the item boundary. Item-failure isolation works because an
exception raised by `scrape_portal()` in `run()` is thrown *into*
the generator at the `yield` — a `try` around the item's inner
loops catches it and `continue` moves to the next item:

```python
# apartment_scraper.py (sketch)
def get_search_urls(self):
    items = self.sync_items()          # Region → ScrapeJobItem
    for item in self.runner.pending_items(items):
        self._current_region = item.region   # see 5.2
        try:
            for suffix, deal_type in DEAL_SUFFIXES.items():
                for page in range(1, self.max_pages + 1):
                    yield region.url + suffix + page_part
                    self.runner.touch()      # per-page heartbeat
                    if not self.last_search_had_results:
                        break
        except Exception as e:
            self.runner.item_failed(item, e)  # row + email alert
            continue                          # next region
        self.runner.item_done(item)           # region finished
```

`run()`/`handle()` wraps the whole loop in try/except for *fatal*
errors only (outside item processing — DB down, config missing) →
`runner.finish('FAILED', tb)` + re-raise. At the end:
`finish('PARTIAL')` if any item failed, else `finish('SUCCESS')`.

### 5.2 Carrying the domain object

`ScrapeJobItem.key` stores the region PK / keyword name / URL.
Give the runner (or each scraper) a `resolve(item)` that returns
the `Region`/`Keyword`/config entry; caching the resolved object on
the item row (`item._region`) keeps `parse_results` untouched
(`self._current_region` is still a `Region`).

### 5.3 Command-layer changes

```python
def handle(self, *args, **options):
    runner = ScrapeJobRunner(
        slug=self.JOB_SLUG,
        cycle_key=options.get('cycle'),
        fresh=options.get('fresh'),
    )
    scraper = ApartmentAdScraper(
        max_pages=options['max_pages'], runner=runner
    )
    try:
        scraper.run()
    except Exception as e:
        runner.finish('FAILED', traceback.format_exc())
        raise
    runner.finish('SUCCESS')
```

New flags on every converted command: `--cycle KEY`, `--fresh`,
`--resume-from KEY` (debug override), `--dry-run` where missing
(blogs already caps AI spend via `AIJob.max_requests_per_run`).

### 5.4 Per-item email alert (terraform/monitoring.tf)

`item_failed()` logs one structured line — e.g.
`logger.error('SCRAPE_ITEM_FAILED job=%s item=%s err=%s', ...)`.
Add one **log-based alert policy** reusing the existing email
channel (no new secrets, no SMTP):

```hcl
resource "google_monitoring_alert_policy" "scrape_item_failure" {
  count        = length(
      google_monitoring_notification_channel.email) > 0 ? 1 : 0
  display_name = "Scrape job item failure"
  combiner     = "OR"

  conditions {
    display_name = "SCRAPE_ITEM_FAILED log entry"
    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_run_job"
        AND severity>=ERROR
        AND textPayload:"SCRAPE_ITEM_FAILED"
      EOT
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email[0].id,
  ]

  alert_strategy {
    notification_rate_limit { period = "300s" }
    auto_close = "86400s"
  }
}
```

Notes: Cloud Run job logs reach Cloud Logging as `textPayload`
automatically — no code-side logging change needed beyond the
marker string. `notification_rate_limit` (300s) caps mail volume
if many items fail in one run — raise/lower to taste. Local runs
never reach Cloud Logging, so item failures locally are log-file
only (acceptable; if local alerting is wanted later, add a guarded
`mail_admins()` call in `item_failed` behind `settings.ADMINS`).

## 6. Item sources & priorities

| Job slug | `sync_items()` maps from | `key` | Default `priority` |
|---|---|---|---|
| `classified_ads.apartment_ads` | `Region(scrape_enabled=True, category='APARTMENT')` | `str(region.id)` | `int(region.order_id)` fallback 0; else region.id |
| `classified_ads.house_ads` | same queryset filtered to `/homes-summer-residences/` urls | `str(region.id)` | same |
| `fetcher.vacancies.<portal_id>` | `Keyword(only_filter=False)` | `keyword.name` | 0 (id order) |
| `blogs.blog_posts` | `config['blog_listing_urls']` | listing URL | yaml position |
| `tv_programs.guide` | `Channel` × date range | `f'{channel}:{date}'` | chronological |

Priority is processed **highest first** (`ordering = ['-priority',
'id']`). Sync = `get_or_create` + label refresh; admin edits to
`priority`/`is_active` are never overwritten (`ensure_job`
precedent). Deleting a `Region`/`Keyword` leaves the item row;
`synch_items` marks rows whose source vanished `is_active=False`
in the item table only — never mutates the domain model.

`scrape_blogs` keeps its config-file URL list (gitignored
`config.yaml`); item rows are just checkpoints, the URL remains the
source of truth. Same for portal config (`FETCHER_PORTALS_JSON`).

## 7. Implementation phases

- **PR-1**: `scrape_jobs` app — models, admin (`ScrapeJobRun`
  changelist shows status/cycle/duration; item inline on job),
  `ScrapeJobRunner` (incl. `item_failed` alert marker), unit tests
  for stale-sweep + pending-items + failure-isolation logic, and
  the log-based alert policy in `terraform/monitoring.tf`.
  *Human runs `makemigrations`/`migrate` — see section 8.*
- **PR-2**: `scrape_apartment_ads` + `scrape_housing_ads` on the
  runner; delete `_get_last_scraped_region_id` from both scrapers
  (superseded — keep sightings writes untouched, they serve
  `days_active` not resume).
- **PR-3**: `scrape_vacancies` — job slug per portal id;
  checkpoint per keyword.
- **PR-4** (optional): `scrape_blogs` (item = listing URL; page-level
  resume inside a listing is out of scope — `Page` dedup makes a
  restarted listing idempotent) and `scrape_tv_programs`
  (item = channel×date).
- **PR-5** (optional): usage view in admin (runs/day, durations,
  abandonment rate) modelled on `ai_providers/usage.py`.

## 8. Guardrails (project-specific)

- **Never run `makemigrations` or `migrate`** — write models and
  ask the user to run them (`.devin/rules/no-migrations.md`).
- Migration PRs must be squash-merged or `run-migrations.yml`
  triggered manually (it diffs `HEAD~1..HEAD`).
- `python manage.py check` + `python manage.py test scrape_jobs`
  (or the touched app) for verification; 79-char lines;
  `logging.getLogger('scrape_jobs')`.
- Scraper commands hit live sites — verify with small `--limit`/
  `--max-pages`/single-cycle runs, not full scrapes.
- `scrape_blogs` spends money per request — the JobClient cap
  still applies on top of checkpointing; a resumed run must
  re-resolve the JobClient (fresh request_count snapshot).
- Nothing here may bypass `BaseScraper.make_request`/`sleep`
  throttling.

## 9. Verification plan

### Phase 0 — local kill test (cheap, run first)

```bash
python manage.py scrape_apartment_ads --max-pages 3
# let 1–2 regions complete, then:
kill -9 <pid>                      # simulate power loss
python manage.py shell -c "
from scrape_jobs.models import ScrapeJobRun, ScrapeJobRunItem
r = ScrapeJobRun.objects.latest('id')
print(r.status, r.last_completed_item_id)
print(ScrapeJobRunItem.objects.filter(run__job=r.job)
    .values_list('item__key', 'status'))"
python manage.py scrape_apartment_ads --max-pages 3
# expect: stale run marked ABANDONED, new run skips completed keys

# per-item failure isolation: temporarily break one item (e.g.
# --resume-from a bogus key, or a test that raises in one item's
# processing) → expect SCRAPE_ITEM_FAILED in logs, run continues,
# ends PARTIAL, failed item NOT in the cycle's skip-set on rerun
```

### Phase 1 — GCP run & interruption

```bash
# confirm the job exists (terraform blocks are commented out —
# the resource may still be live thanks to prevent_destroy)
gcloud run jobs list --region europe-north1

gcloud run jobs execute scrape-apartment-ads --region europe-north1
# note the execution name from the output; wait 1–2 min so several
# region checkpoints land, then CANCEL (not 'stop'):
gcloud run jobs executions cancel <EXECUTION_NAME> \
    --region europe-north1
```

### Phase 2 — log & DB verification

```bash
gcloud logging read \
  'resource.type="cloud_run_job"
   AND resource.labels.job_name="scrape-apartment-ads"' \
  --limit 50 --format json

python manage.py shell   # against the prod DATABASE_URL
```
```python
from scrape_jobs.models import ScrapeJob, ScrapeJobRun
job = ScrapeJob.objects.get(slug='classified_ads.apartment_ads')
for r in job.runs.order_by('-id')[:5]:
    print(r.execution_id, r.executed_by, r.status,
          r.last_completed_item_id, r.updated_at)
# cancelled run shows RUNNING→ABANDONED (on next sweep) and a
# last_completed_item; ScrapeJobRunItem rows = completed regions
```

### Phase 3 — resumption

```bash
gcloud run jobs execute scrape-apartment-ads --region europe-north1
```
- Logs must show "resuming cycle <today>" and skipped keys.
- `ScrapeJobRunItem` across the cancelled and new runs covers the
  item list with no key processed twice (spot-check region sightings
  timestamps if paranoid — re-scrape is still idempotent by design).
- **Alert check**: force one item failure on GCP (or inject one);
  confirm a `SCRAPE_ITEM_FAILED` entry in `gcloud logging read` and
  an alert email arrives within a few minutes, while the execution
  itself continues and completes (status `PARTIAL` in DB).

### Rollback

Feature-flag via `ScrapeJob.is_enabled=False` + `--fresh`: runner
degenerates to a full pass, commands behave exactly as today.

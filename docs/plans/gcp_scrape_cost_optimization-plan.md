# GCP Scrape Cost Optimization — Plan

Status: implemented

Cut Cloud Run cost of the daily `all-jobs` job by turning every
scrape on GCP into a *fallback*: it runs only when the data has
actually gone stale (no local SUCCESS recently / program horizon
collapsed), and it skips the AI-OCR path that fails ~92% of its
attempts. Local scraping behavior is unchanged.

Scope: JOBS schedules + per-command gating flags only. No data-model
changes, no migrations, no terraform changes (the
`all-jobs-daily` 19:50 UTC trigger in `terraform/main.tf:213-236`
stays as-is — per-job gating lives in `run_all_jobs`).

## 1. Findings (verified)

### 1.1 How GCP scheduling works today

- Cloud Scheduler `all-jobs-daily` fires 19:50 UTC daily → Cloud Run
  job `all-jobs` → `python manage.py run_all_jobs`
  (`scrape_jobs/management/commands/run_all_jobs.py`). Its `JOBS`
  list (lines 44-67) is the only schedule; `is_due()` (lines
  75-131) supports `daily`, `local:<sched>`, `weekly:<dow>`,
  `dom:odd`, `dom:<N>`, `last_day_of_month`, `manual`. `--dry-run`
  prints `RUN`/`skip` per entry with argv+schedule (lines
  257-262) — schedule-level only; per-command gates decide at
  runtime.
- `scrape_jobs/runner.py` already provides the "GCP as fallback"
  primitive: `cooldown_skip_reason(slug, executed_by, cycle_key,
  days)` (lines 151-177). On `gcp_cloud_run` it returns a skip
  reason when ANY executor's SUCCESS run completed within `days`
  (`recent_scrape_exists`, lines 117-132 — no `executed_by`
  filter, so local successes suppress GCP) or a live RUNNING run
  exists. On `local` it only skips a same-cycle SUCCESS. The gate
  runs *before* `ScrapeJobRunner(...)` construction, so a skipped
  pass writes no `ScrapeJobRun` row.
- `detect_executed_by()` (runner.py:52-68) returns
  `gcp_cloud_run` on Cloud Run; `cycle_key` defaults to the UTC
  date for classified_ads/tv and `iso_week_cycle_key()` for
  vacancies.
- `ScrapeJobItem.is_active` is admin-owned: `sync_items` marks
  absent keys inactive and never reactivates (runner.py:273-321).

### 1.2 JOBS table — current vs proposed

| JOBS label | Now | Proposed |
|---|---|---|
| `sync_receipt_emails` | `last_day_of_month` | unchanged |
| `scrape_tv_programs` | `dom:odd` | `daily` + gate §3 |
| `scrape_housing_ads` | `dom:odd` | `daily` + cooldown §2 |
| `scrape_apartment_ads` | `dom:odd` | `daily` + cooldown §2 |
| `scrape_vacancy` | `manual` | `daily` + §4 |
| `link_ads_to_properties` | `dom:odd` | `daily` |
| news pipeline (3 jobs) | `local:daily` | unchanged |
| `scrape_blogs` | not in JOBS | unchanged |

GCP cost when an entry actually runs today:

- `scrape_tv_programs` — ~3-10 min of real work on days local did
  not scrape; ~2 s no-op when it did (cycle dedup finds all 42
  channel:date items DONE). Proposed gate also adds
  `--days-past 1`.
- `scrape_housing_ads` — ~30-40 min full scrape.
- `scrape_apartment_ads` — ~60-90 min full scrape.
- `scrape_vacancy` — never runs on GCP today (`manual`). Its
  dominant cost driver would be the `fetcher.vacancy_image_ocr`
  AI job; proposed run adds a per-portal 13-day cooldown and
  `--no-ocr`.
- `link_ads_to_properties` — cheap DB-only pass.
- News pipeline — ~0.1 min/run but already `local:`-gated.

### 1.3 Data windows supporting the cadences

- Sighting-based ad lifespans: apt_rent median 7 d / avg 19 d;
  apt_sale 22 d/33 d; house_rent 20 d/30 d; house_sale 28 d/38 d.
  A 7-day fallback may lose ~1 week of sightings for the shortest
  rent ads, but most ads live 3-5 weeks — acceptable for a
  fallback.
- TV: 3 channels (`filmzone_hd`, `ltv1_hd`, `ltv7_hd` —
  `tv_programs/scraper.py:39-43`) x 14-day window. EPG horizon is
  ~6 days ahead, so a horizon gate only engages ~5 days after the
  last local run; daily re-checks give the "retry every ~5-7 days"
  behavior for free.
- Vacancies: ~49k rows; median open span ~8 d for closed ads, p90
  ~28 d, avg `application_deadline` +25.5 d → a ~2-week GCP
  fallback is reasonable; ads open <14 days may be missed between
  fallback runs (accepted).
- `fetcher.vacancy_image_ocr` AI job: 6,916 attempts, 92% failed
  (4,911 `AIRateLimitError`, 1,080 `AIEmptyResponseError`) —
  dominant vacancy cost driver on GCP.

## 2. Change A — classified ads: 7-day GCP fallback

Files:

- `classified_ads/management/commands/scrape_apartment_ads.py`
- `classified_ads/management/commands/scrape_housing_ads.py`

Both files are identical in shape. In each:

1. `GCP_COOLDOWN_DAYS = 1` (line 19) → `7`; rewrite the comment
   above it (lines 16-18) — the "every other day (dom:odd)"
   rationale no longer holds:

   ```python
   # GCP Cloud Run is the weekly fallback: scrape only when no
   # SUCCESS (local or GCP) completed in the last 7 days. The
   # JOBS entry runs `daily` so the fallback engages on any day
   # the data goes stale, not just odd days.
   GCP_COOLDOWN_DAYS = 7
   ```

2. `--ignore-cooldown` help text (lines 61-63): `(1 day on GCP,`
   → `(7 days on GCP,`.

3. `run_all_jobs.py` JOBS: `'dom:odd'` → `'daily'` on the
   `scrape_housing_ads` and `scrape_apartment_ads` entries.

No logic changes — the existing gate at `handle()` (lines 66-80)
already bypasses on `--ignore-cooldown`/`--fresh`/`--dry-run`,
runs before `ScrapeJobRunner` (no run row on skip), and counts
local+GCP successes.

Edge cases:

- A GCP SUCCESS then self-cools GCP for 7 days → "at most once a
  week" holds even while local is off.
- FAILED/PARTIAL/ABANDONED runs never satisfy the gate → GCP
  retries on the next daily invocation.
- Local path unchanged: `cycle_scrape_exists` still gates only the
  same-day cycle.

### `link_ads_to_properties` schedule

Change `dom:odd` → `daily` as well. Justification: it is pure DB
work (no HTTP) and idempotent — it only touches
`property_match_status='unmatched'` ads, and `--older-than-days 3`
just defers the freshest ads (`first_seen` < 3 days old; it does
not shrink the backlog). On an empty queryset it costs one query
per table; running daily means ads scraped by a fallback GCP run
on an even day enter the linking pipeline next morning instead of
waiting for the next odd day. Update the "Linking runs on the
same odd-day pass" comment in JOBS accordingly.

### Tests

`classified_ads/tests.py` `GcpFallbackCooldownTest` (~line 1137):

- Docstring says "within the last 6 days" — update to 7 days.
- `test_apartment_gcp_scrapes_after_stale_success` uses
  `timedelta(days=7)` (line 1193) — under the new window that is
  exactly the boundary (`completed_at__gte=now-7d`); bump to
  `days=8` so the test asserts a *clearly* stale success.
- Existing `skips_after_recent_success` tests (completed `now()`)
  still cover the within-window case.

## 3. Change B — TV programs: daily + data-horizon gate

Business need: yesterday + today data fresh. GCP should scrape
only when stored coverage has actually collapsed, then re-check
every day until it succeeds.

Files:

- `tv_programs/scraper.py`
- `tv_programs/management/commands/scrape_tv_programs.py`
- `run_all_jobs.py` JOBS entry

Steps:

1. `tv_programs/scraper.py`: lift the hardcoded channel dict
   (lines 39-43) to a module constant so the gate iterates the
   same names without instantiating the scraper:

   ```python
   CHANNELS = {
       "filmzone_hd": "filmzone_hd",
       "ltv7_hd": "ltv7_hd",
       "ltv1_hd": "ltv1_hd",
   }
   ```

   `__init__` then does `self.channels = dict(CHANNELS)`.

2. `scrape_tv_programs.py`: add imports —
   `from datetime import timedelta`,
   `from django.db.models import Max`,
   `from scrape_jobs.runner import ScrapeJobRunner,
   detect_executed_by`,
   `from tv_programs.models import Program`, and
   `from tv_programs.scraper import TVProgramScraper, CHANNELS`.

3. Add a module-level helper (returns a skip reason or `None`):

   ```python
   def _gcp_horizon_skip_reason():
       """GCP-only gate: scrape only when stored coverage no
       longer reaches at least tomorrow (+1 day buffer)."""
       tomorrow = timezone.localdate() + timedelta(days=1)
       for name in CHANNELS:
           latest = Program.objects.filter(
               channel__name=name
           ).aggregate(m=Max('start_time'))['m']
           if latest is None or latest.date() < tomorrow:
               return None
       return (
           'every channel has program coverage through '
           f'{tomorrow} or later; GCP run is a fallback'
       )
   ```

   Notes:
   - `Program.start_time` is a `DateTimeField`
     (`tv_programs/models.py:54`); `TIME_ZONE=UTC`, so
     `latest.date()` is the same UTC date basis `cycle_key` uses.
   - A channel with **zero** Program rows → `latest is None` →
     treated as uncovered → scrape proceeds (a brand-new/empty
     channel can never block the fallback).
   - One uncovered channel is enough to scrape (the check is
     "skip only when *every* channel is covered").

4. In `handle()`, before `ScrapeJobRunner(...)` (line 74):

   ```python
   if not (
       options['force'] or options['fresh']
       or options['dry_run']
   ) and detect_executed_by() == 'gcp_cloud_run':
       reason = _gcp_horizon_skip_reason()
       if reason:
           msg = f'tv_programs.guide: skipping — {reason}'
           logger.info(msg)
           self.stdout.write(msg)
           return
   ```

   Bypass ordering mirrors classified_ads: flags first, gate
   second, runner last. `--force` ("scrape regardless of existing
   data") is the documented manual override — no new flag needed.
   The gate never evaluates locally and runs before the runner,
   so a skip writes no run row; `--dry-run` bypasses so the flag
   still exercises a full no-write pass.

5. JOBS entry:

   ```python
   ('scrape_tv_programs', 'command', ['--days-past', '1'],
    'daily'),
   ```

   `--days-past 1` cuts the fetch window from 14 days (42
   channel:date items) to 8 (~24 pages) on fallback runs —
   business need is yesterday+today. Trade-off: past-day
   corrections older than 1 day are only refreshed by local runs;
   acceptable since local is primary.
   Caveat: JOBS argv applies to *any* executor running
   `run_all_jobs` — a hypothetical local `run_all_jobs` pass also
   gets `--days-past 1`. Direct `manage.py scrape_tv_programs`
   keeps the defaults either way.

6. Optional, separate small fix: the window is off-by-one —
   `range(days_in_past + days_in_future)` at `scraper.py:121`
   yields today−7…today+6, not +7. `+ 1` inside `range()` fixes
   it. New `channel:date` keys appear via `sync_items` (created
   active; out-of-window keys get deactivated). Ship as its own
   commit — it changes the item set and is not required for the
   cost goal.

### Tests (`tv_programs/tests.py`, new test class)

Follow the `_invoke` pattern from
`classified_ads/tests.py:1164-1172`: patch
`tv_programs.management.commands.scrape_tv_programs
.detect_executed_by` (module-level import → patch where it is
looked up) and mock `TVProgramScraper`.

- GCP + `Program` rows through tomorrow on all channels → scraper
  not called, **no new `ScrapeJobRun` row**.
- GCP + coverage only through today (or no rows at all) → scraper
  runs.
- Local executor + full coverage → scraper still runs (gate never
  evaluates locally).
- GCP + full coverage + `--force` → scraper runs.

## 4. Change C — vacancies: daily, per-portal cooldown, `--no-ocr`

Files:

- `fetcher/management/commands/scrape_vacancies.py`
- `scripts/materialize_fetcher_config_and_scrape.py`
- `run_all_jobs.py` JOBS entry

Steps in `scrape_vacancies.py`:

1. Add imports: `import logging`,
   `from scrape_jobs.runner import (ScrapeJobRunner,
   cooldown_skip_reason, detect_executed_by, iso_week_cycle_key)`,
   and `logger = logging.getLogger('fetcher')` (app-named logger
   per repo convention — the file has none today).

2. Module constants:

   ```python
   # GCP Cloud Run is the ~2-week fallback: sweep a portal only
   # when it had no SUCCESS (local or GCP) in the last 13 days.
   GCP_COOLDOWN_DAYS = 13
   ```

3. New arguments (parity with classified_ads / refetch):

   ```python
   parser.add_argument(
       '--ignore-cooldown', action='store_true',
       dest='ignore_cooldown',
       help='Run even if a scrape already succeeded in the '
            'cooldown window (13 days on GCP, current ISO week '
            'locally)',
   )
   parser.add_argument(
       '--no-ocr', action='store_true',
       help='Skip fetching/AI-transcribing attached files; '
            'cached VacancyFile text is still reused.',
   )
   ```

4. In `handle()`: compute the cycle key once —
   `cycle_key = options['cycle'] or iso_week_cycle_key()` — and
   reuse it for the gate *and* the `ScrapeJobRunner` call so both
   see the same cycle. Inside the `for pid in portal_ids:` loop,
   before constructing the runner:

   ```python
   slug = f'fetcher.vacancies.{pid}'
   if not (
       options['ignore_cooldown']
       or options['fresh']
       or options['dry_run']
   ):
       reason = cooldown_skip_reason(
           slug, detect_executed_by(), cycle_key,
           days=GCP_COOLDOWN_DAYS,
       )
       if reason:
           msg = f'{slug}: skipping — {reason}'
           logger.info(msg)
           self.stdout.write(msg)
           continue
   ```

   Per-portal, not per-invocation: the runner slug is
   `fetcher.vacancies.{pid}`, so each portal cools down
   independently — one portal's SUCCESS must not suppress the
   other.

5. After `scraper = VacancyScrapper(portal_id=pid, ...)`:

   ```python
   if options['no_ocr']:
       # Same switch as refetch_vacancies: cached VacancyFile
       # text is still reused (the cache lookup in
       # _ocr_vacancy_file precedes this early-out), but no
       # file fetch or AI call happens.
       scraper._ocr_unavailable = True
   ```

   Verified in `fetcher/scraper.py`: `VacancyFile` cache hit at
   lines 349-353 returns before the `_ocr_unavailable` early
   return at line 354; the AI call path (lines 374-401) is only
   reached for unknown file_ids. Job spec:
   `fetcher/ai_jobs.py` `VACANCY_IMAGE_OCR`; the flag mirrors
   `refetch_vacancies.py:114-117,170-174`.

Steps in `scripts/materialize_fetcher_config_and_scrape.py`:

The script currently treats `sys.argv[1]` as an optional portal-id
filter (lines 33-38) and cannot forward flags — passing
`--no-ocr` in JOBS argv today would hit the "portal --no-ocr not
configured" error path. Split argv: tokens starting with `-` are
forwarded verbatim to each `manage.py scrape_vacancies <pid>`
call; the first non-flag token keeps working as the portal
filter:

```python
args = sys.argv[1:]
flags = [a for a in args if a.startswith('-')]
positional = [a for a in args if not a.startswith('-')]
only = positional[0] if positional else None
# ... existing 'only' filtering ...
rc |= subprocess.call(
    [sys.executable, str(BASE / "manage.py"),
     "scrape_vacancies", str(portal_id), *flags],
    cwd=str(BASE),
)
```

JOBS entry:

```python
('scrape_vacancy', 'script',
 ['scripts/materialize_fetcher_config_and_scrape.py',
  '--no-ocr'], 'daily'),
```

Edge cases:

- First-ever GCP run for a portal: no `ScrapeJob` row →
  `recent_scrape_exists` returns False → scrape proceeds, creates
  job+run, then self-cools for 13 days.
- FAILED/PARTIAL/ABANDONED runs never satisfy
  `recent_scrape_exists` (SUCCESS-only + live RUNNING) → a portal
  whose last run failed is retried on the next daily pass.
- Local gate = `cycle_scrape_exists(slug, cycle_key)` with the
  ISO-week key — a same-week local SUCCESS now exits before
  creating a run row (previously it constructed a runner and
  walked an empty pending set). Same net behavior — no re-scrape —
  just cheaper; mention in commit message.
- `--resume-from` alone does **not** bypass the gate (same as
  classified_ads); combine with `--fresh`/`--ignore-cooldown`.
- `--dry-run` bypasses and writes nothing — `ScrapeJobRunner`
  `dry_run=True` never creates run/item rows (runner.py:200-210).
- `--no-ocr` applies whenever the flag is passed, including local
  — it is only wired into the GCP JOBS argv, so local cadence is
  untouched.

### Tests (`fetcher/tests.py`)

- Patch `...scrape_vacancies.detect_executed_by` +
  `VacancyScrapper`/`load_portals_config` (or pass `portal_id`):
  SUCCESS 13 d ago → scrape; SUCCESS now → skip, no run row;
  last run FAILED → scrape.
- `--no-ocr` sets `scraper._ocr_unavailable` — existing OCR tests
  (e.g. `test_request_cap_marks_ocr_unavailable`, ~line 446) show
  the stub-client pattern.

## 5. JOBS diff (`run_all_jobs.py`)

Before:

```python
('scrape_tv_programs', 'command', [], 'dom:odd'),
('scrape_housing_ads', 'command', [], 'dom:odd'),
('scrape_apartment_ads', 'command', [], 'dom:odd'),
('scrape_vacancy', 'script',
 ['scripts/materialize_fetcher_config_and_scrape.py'], 'manual'),
# Linking runs on the same odd-day pass, right after the
# classified-ads scrapes above (scrape_vacancy stays manual).
('link_ads_to_properties', 'command', ['--older-than-days', '3'],
 'dom:odd'),
```

After:

```python
('scrape_tv_programs', 'command', ['--days-past', '1'], 'daily'),
('scrape_housing_ads', 'command', [], 'daily'),
('scrape_apartment_ads', 'command', [], 'daily'),
('scrape_vacancy', 'script',
 ['scripts/materialize_fetcher_config_and_scrape.py',
  '--no-ocr'], 'daily'),
# Linking runs daily too — cheap DB-only pass that follows
# whichever day a fallback scrape actually ran.
('link_ads_to_properties', 'command', ['--older-than-days', '3'],
 'daily'),
```

`sync_receipt_emails` and the three `local:daily` news entries
are untouched. No new schedule keyword is needed — `daily`
already exists.

## 6. Verification

```bash
python manage.py check
python manage.py run_all_jobs --dry-run   # prints RUN/skip per
                                        # entry incl. new argv
DATABASE_URL=sqlite:///db.sqlite3 \
    python manage.py test classified_ads scrape_jobs tv_programs \
    fetcher
```

- `run_all_jobs --dry-run` shows schedule-level due-ness only —
  e.g. `RUN scrape_tv_programs` prints even when the horizon gate
  would skip it at runtime; the gate's `skipping —` log line is
  the real decision. Check
  `scrape_jobs/tests/test_run_all_jobs.py` (esp.
  `test_dry_run_prints_plan_and_runs_nothing`, ~line 174, and
  `test_all_jobs_schedules_parse`, ~line 93) — update any
  assertions that hardcode the old schedules/argv.
- Cooldown/horizon gates cannot be exercised by date alone —
  tests mock `detect_executed_by` (existing `_invoke` pattern,
  `classified_ads/tests.py:1164-1172`) or use the documented
  flags: `--ignore-cooldown` (ads, vacancies), `--force` (tv),
  `--fresh`/`--dry-run` (all three commands).
- Local sanity: `python manage.py scrape_vacancies --dry-run`,
  `scrape_tv_programs --dry-run`, `scrape_apartment_ads
  --dry-run` must all bypass their gates and write no run rows.
- Post-deploy GCP check: `gcloud run jobs execute all-jobs`,
  then confirm logs show `skipping —` for every scrape entry
  while local runs are current.

Also update `AGENTS.md` where it describes the `run_all_jobs`
JOBS/schedules and the `scrape_vacancies` flag list (new
`--no-ocr`/`--ignore-cooldown`).

## 7. Out of scope

- News pipeline — already `local:daily`, never on GCP.
- `scrape_blogs` — not in JOBS (unscheduled).
- `sync_receipt_emails` — `last_day_of_month`, rare.
- Terraform / scheduler — the 19:50 UTC daily trigger is
  unchanged; all gating is application-level.
- TV `range()` off-by-one (today−7…+6 vs +7) — noted in §3 step 6;
  ship separately.
- No model/schema changes; no migrations.

## 8. Rollback

Revert the `JOBS` list (schedules + argv) in `run_all_jobs.py`
and the `GCP_COOLDOWN_DAYS` values in the two classified_ads
commands — that alone restores today's timing. The new flags
(`--ignore-cooldown`, `--no-ocr`), the TV horizon helper and the
`CHANNELS` constant are inert when not invoked; the script's flag
forwarding is backward-compatible (no flags → old behavior).

# Design

## Context

The news pipeline is four independent management commands
(`scrape_news`, `link_news_stories`,
`reclassify_news_articles`, `build_news_digest`) that must run
in order daily. `run_all_jobs` lists them as four
`local:daily` entries, but the maintainer's machine schedules
commands individually — only `scrape_news` ran, so articles
piled up `unmatched` and digests/Google tasks stopped.
`ScrapeJobRunner` already provides cycle-scoped item
checkpointing (`sync_items` / `pending_items` / `item_done` /
`item_failed` / PARTIAL finish), normally driven by a
`BaseScraper` per-item loop — but nothing requires items to
be portal work; a job item can be any named unit.

## Goals / Non-Goals

**Goals:**
- One command (`news_pipeline`) = one cron entry = the whole
  daily chain, resumable at phase granularity.
- Reuse `ScrapeJobRunner` bookkeeping so pipeline state is
  visible on the existing `/dashboard/` scrape-jobs UI.
- Keep the four delegated commands unchanged and directly
  usable.

**Non-Goals:**
- No new models/migrations (existing `scrape_job*` tables).
- No changes to the delegated commands' internals or the
  `--backfill` path.
- No automatic retry/backoff inside a run — the next
  scheduled invocation is the retry.

## Decisions

### 1. New `news_pipeline` command, not a `scrape_news` flag

`scrape_news` already has a crowded flag surface
(`--backfill`, `--since`, `--source`, cooldowns). A separate
command keeps the daily entry point obvious and leaves
`scrape_news` usable standalone for targeted runs.

### 2. Phases checkpointed as ScrapeJobItems, not a new table

`runner.sync_items` upserts four items —
`scrape`, `link`, `reclassify`, `digest` with priorities
40/30/20/10 (descending priority = execution order in
`pending_items`). DONE keys in the cycle's completed set are
skipped automatically, giving the resume semantics for free;
the run row heartbeats via `item_done`. Alternative — a
`news_pipeline_state` table — was rejected: it duplicates
machinery that already exists and is admin-visible.

### 3. Delegate via `call_command`, abort on first failure

Each phase calls `call_command(<name>, *argv)` — the same
invocation `run_all_jobs` uses, preserving each command's own
arg handling and `CommandError` surface. The pipeline aborts
at the first failed phase: downstream phases on stale data
would produce misleading digests, and the failed item stays
non-DONE so the next invocation resumes there. (Alternative —
continue past failures like scraper item isolation — was
rejected: the phases are dependent, not independent work
units.)

### 4. `scrape_news` nested runner + cooldown is a feature

The scrape phase invokes `scrape_news`, which opens its own
`news.feeds` run with per-feed items and the local
same-cycle SUCCESS gate. Inside the pipeline this means: a
same-day `scrape_news` already done exits cheaply (phase
still marked DONE — articles exist), and a feed-level failure
propagates as `CommandError` → phase FAILED. `--fresh` on the
pipeline forwards `--fresh` to `scrape_news` to bypass its
gate and re-parse feeds.

### 5. `--dry-run` lists the plan only

`ScrapeJobRunner(dry_run=True)` writes no job/run/item rows;
the command prints pending phase keys and exits without
invoking any delegated command (unlike the commands' own
dry-runs, which still hit the network — not what a scheduler
sanity-check wants). `--from PHASE` maps onto the runner's
`resume_from` item-key mechanism; unknown keys raise the
runner's `ValueError` → `CommandError`.

## Risks / Trade-offs

- [A multi-day outage leaves articles older than
  `link_news_stories --days 2`'s window unmatched] → On
  catch-up the maintainer runs
  `link_news_stories --days N` once; documented in
  docs/news_pipeline.md.
- [Pipeline run while a `news.feeds` scrape is already
  RUNNING gets skipped by scrape_news's live-run gate; the
  scrape phase would still be marked DONE] → Acceptable: the
  in-flight run produces the articles; next day resumes
  normally.
- [Digest for a day the pipeline missed is never built
  retroactively] → `build_news_digest --date D` stays the
  backfill tool; noted in docs.

## Migration Plan

Merge → maintainer applies nothing (no migrations) → swap
the Linux schedule's `scrape_news` entry for `news_pipeline`
(or point it at `run_all_jobs`). Rollback: re-add the four
JOBS entries / schedule the commands individually — the
pipeline command is additive.

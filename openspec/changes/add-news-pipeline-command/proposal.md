# Proposal

## Why

The daily news pipeline is four separate management commands —
`scrape_news` → `link_news_stories` → `reclassify_news_articles`
→ `build_news_digest` — that must run in order for `/news/`
digests and their Google tasks to appear. In practice only
`scrape_news` was scheduled on the maintainer's machine, so
articles accumulated `unmatched` for days while stories,
digests and Google tasks silently stopped. One scheduled job
that owns the whole pipeline removes the foot-gun, and reusing
the existing cycle-scoped ScrapeJob checkpointing gives
resume-after-failure and same-day idempotency for free.

## What Changes

- New `news_pipeline` management command (news app) that runs
  the four phases in order under one ScrapeJob
  (`news.pipeline`), checkpointing each phase as a job item so
  a re-invocation in the same cycle resumes at the first
  unfinished phase.
- `run_all_jobs` JOBS: replace the four `local:daily` news
  entries with a single `('news_pipeline', 'command', [],
  'local:daily')` entry.
- `--fresh` re-runs every phase (and forwards `--fresh` to
  `scrape_news`); `--dry-run` prints pending phases without
  invoking anything; `--from PHASE` resumes at a chosen phase.
- Tests for phase order, same-cycle resume, failure abort,
  dry-run and the updated `run_all_jobs` JOBS list.

## Capabilities

### New Capabilities
- `news-pipeline`: the single stateful daily command that
  orchestrates the news scrape-to-digest phases with
  cycle-scoped resume and idempotent re-runs.

### Modified Capabilities
<!-- The four delegated commands keep their own behavior; only
     run_all_jobs' membership changes, which has no existing
     spec. -->

## Impact

Backend only. Touched code: new
`news/management/commands/news_pipeline.py`,
`scrape_jobs/management/commands/run_all_jobs.py` (JOBS list),
`news/tests.py`, `scrape_jobs/tests/test_run_all_jobs.py`
(expected label lists), `docs/news_pipeline.md` and AGENTS.md
command references. No model changes — reuses existing
`scrape_job*` bookkeeping tables, so no migration. No API or
frontend changes. The maintainer's Linux schedule switches
from `scrape_news` to `news_pipeline` (or `run_all_jobs`) to
get the full chain daily.

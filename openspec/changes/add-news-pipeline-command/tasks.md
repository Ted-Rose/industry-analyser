# Tasks

## 1. Pipeline command

- [x] 1.1 backend: Create
  `news/management/commands/news_pipeline.py` — a
  `ScrapeJobRunner` (slug `news.pipeline`, daily cycle) with
  four synced items `scrape`/`link`/`reclassify`/`digest`
  (priorities 40/30/20/10) that invokes each delegated
  command via `call_command` in order, `item_done` on
  success, `item_failed` + abort on failure (run ends
  PARTIAL). Verify: `python manage.py news_pipeline
  --dry-run` prints all four phases pending.
- [x] 1.2 backend: Add `--fresh` (runner fresh + forwards
  `--fresh` to `scrape_news`), `--from PHASE` (runner
  `resume_from`, unknown key → CommandError) and `--dry-run`
  (lists pending phases, no invocation, no bookkeeping
  writes). Verify: `python manage.py check` passes and
  `--dry-run` creates no `scrape_job_run` row (assert in
  test).

## 2. Pipeline tests

- [x] 2.1 backend: Add tests in `news/tests.py` (mirroring
  the `scrape_news` runner-test style): phase order via
  mocked `call_command`; second same-cycle invocation skips
  DONE phases; a raising phase records the item FAILED,
  aborts later phases and finishes PARTIAL; `--from digest`
  runs only the digest phase; `--dry-run` invokes nothing
  and writes nothing. Verify:
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
  news` passes.

## 3. run_all_jobs membership

- [x] 3.1 backend: In `scrape_jobs/management/commands/
  run_all_jobs.py` replace the four `local:daily` news
  entries (`scrape_news`, `link_news_stories`,
  `reclassify_news_articles`, `build_news_digest`) with one
  `('news_pipeline', 'command', [], 'local:daily')`. Verify:
  `python manage.py run_all_jobs --dry-run` shows
  `RUN news_pipeline` locally and the four old labels are
  gone.
- [x] 3.2 backend: Update `scrape_jobs/tests/
  test_run_all_jobs.py` expected label lists/order to the
  new single entry. Verify:
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
  scrape_jobs` passes.

## 4. Docs

- [x] 4.1 backend: Update `docs/news_pipeline.md` (pipeline
  overview + commands section) and AGENTS.md's command
  reference so the documented daily entry point is
  `news_pipeline` (delegated commands documented as
  standalone/backfill tools, incl. catch-up
  `link_news_stories --days N` after an outage). Verify:
  documented commands match real flags.

## Workflow follow-up

- Maintainer swaps the Linux schedule's `scrape_news` entry
  for `python manage.py news_pipeline`.
- Archive the change after merge.

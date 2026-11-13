# Spec Delta

## Purpose

One scheduled entry point that drives the whole daily news
pipeline — feed scrape, story clustering, topic
reclassification and digest build — as a stateful sequence
that resumes where it left off and is safe to re-run.

## ADDED Requirements

### Requirement: Ordered phase execution

`news_pipeline` SHALL run the news pipeline as four ordered
phases: RSS scrape, story linking, topic reclassification,
digest build. Each phase SHALL delegate to its existing
management command so phase behavior stays identical whether
invoked directly or via the pipeline.

#### Scenario: Happy path runs every phase in order

- **WHEN** `news_pipeline` runs with all phases pending
- **THEN** it invokes `scrape_news`, `link_news_stories`,
  `reclassify_news_articles` and `build_news_digest` in that
  order, and each phase completes before the next starts

### Requirement: Cycle-scoped phase checkpointing

Each phase SHALL be recorded as a job item of a ScrapeJob
`news.pipeline` under the daily cycle key; a completed phase
is marked DONE and skipped on later invocations in the same
cycle, so re-running the command resumes at the first
unfinished phase instead of repeating finished work.

#### Scenario: Resume after an interrupted run

- **WHEN** a run completed the scrape and linking phases but
  stopped before reclassification
- **THEN** the next `news_pipeline` invocation in the same
  cycle processes only reclassification and digest build

#### Scenario: Same-cycle re-run of a finished pipeline

- **WHEN** `news_pipeline` is invoked again after every phase
  completed in the current cycle
- **THEN** no phase executes and the run finishes without
  re-scraping, re-linking or rebuilding the digest

### Requirement: Failure aborts at the failed phase

A phase that raises SHALL be recorded FAILED for the run, the
pipeline SHALL abort without running later phases, and the
run SHALL end PARTIAL so the next invocation retries that
phase rather than skipping it.

#### Scenario: Scrape phase fails

- **WHEN** `scrape_news` raises during the pipeline
- **THEN** linking, reclassification and digest build do not
  run, the scrape phase is recorded FAILED, and a subsequent
  invocation in the same cycle retries the scrape phase

### Requirement: Idempotent output

Repeated `news_pipeline` invocations SHALL NOT create
duplicate articles, stories, digest items or Google tasks —
dedup is delegated to the underlying commands
(`unique_together` on news_article, unmatched-only linking,
`update_or_create` digest rebuild and `NewsDigestTask`
`status='created'` dedup).

#### Scenario: Pipeline runs twice in one day

- **WHEN** `news_pipeline` completes and is invoked again the
  same day without `--fresh`
- **THEN** the `news_article`, `news_story`,
  `news_digest_item` and `news_digest_task` row counts are
  unchanged

### Requirement: Fresh and targeted overrides

`--fresh` SHALL make every phase eligible again and forward
`--fresh` to `scrape_news` so feeds are re-fetched;
`--from PHASE` SHALL resume at the named phase and skip
earlier ones; `--dry-run` SHALL list the pending phases
without invoking any command or writing job bookkeeping.

#### Scenario: Fresh re-run

- **WHEN** `news_pipeline --fresh` runs in a cycle where all
  phases are DONE
- **THEN** all four phases execute again in order

#### Scenario: Resume from a named phase

- **WHEN** `news_pipeline --from digest` runs
- **THEN** only the digest phase executes

#### Scenario: Dry-run prints the plan

- **WHEN** `news_pipeline --dry-run` runs
- **THEN** it prints which phases are pending and creates no
  `scrape_job_run` row and invokes no pipeline command

### Requirement: Master-job membership

`run_all_jobs` SHALL schedule `news_pipeline` as a single
`local:daily` entry in place of separate entries for the four
delegated commands, keeping the whole chain local-only —
Cloud Run executions MUST never run it.

#### Scenario: Local pass runs the pipeline

- **WHEN** `run_all_jobs` executes locally
- **THEN** the `news_pipeline` entry is due and the four
  individual news commands have no separate entries

#### Scenario: Cloud Run pass skips the pipeline

- **WHEN** `run_all_jobs` executes on Cloud Run
- **THEN** the `news_pipeline` entry is not due

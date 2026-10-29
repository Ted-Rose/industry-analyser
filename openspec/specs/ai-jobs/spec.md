# AI Jobs Specification

## Purpose

Defines the `ai_providers` contract: the database is the single
source of truth for which provider/model each AI job uses, code
declares jobs as `AIJobSpec`s in `<app>/ai_jobs.py`, and
`JobClient` sends prompts with per-run snapshots, attempt-based
caps, retries, fallback, and complete request logging.

## Requirements

### Requirement: Database is the source of truth

Which provider/model serves each AI job SHALL be resolved from
the `ai_provider`/`ai_model`/`ai_job`/`ai_job_model` tables —
Django admin is the configuration UI. Code-side `AIJobSpec`
declarations in `<app>/ai_jobs.py` (a `JOB_SPECS` list and/or
bare `AIJobSpec` attributes) only seed rows.

#### Scenario: ensure_job on first use

- **WHEN** `ensure_job(spec)` runs and no `AIJob` row exists for
  the spec's slug
- **THEN** the row is created and the spec's
  `default_assignments` become active `AIJobModel` rows whose
  `priority` is their list position

#### Scenario: Admin edits are never overwritten

- **WHEN** `ensure_job(spec)` runs and the `AIJob` row already
  exists
- **THEN** only `description` and `declared_roles` are synced
  from the spec; assignments, caps, and `is_enabled` are left
  untouched

#### Scenario: Seeding is idempotent

- **WHEN** `manage.py seed_ai_config` runs repeatedly
- **THEN** it creates only missing provider/job rows and never
  overwrites existing ones

### Requirement: JobClient snapshot per run

`JobClient` SHALL resolve its job's active assignments (model
and provider `is_enabled`, ordered by `priority`/`id`), caps,
and today's sent count ONCE at construction — admin changes
apply to the next client, not mid-run. Constructing a client
for a disabled job SHALL raise `AIJobDisabledError`.

#### Scenario: Run cap combines job row and client argument

- **WHEN** `get_job_client(spec_or_slug,
  max_requests_per_run=N)` is called
- **THEN** the effective per-run cap is the lower of
  `AIJob.max_requests_per_run` and `N` (unset when both are
  `None`)

#### Scenario: Day cap is soft

- **WHEN** `AIJob.max_requests_per_day` is set
- **THEN** the count of today's `AIRequest` rows is snapshotted
  at construction and incremented in memory — concurrent runs
  may overshoot slightly

### Requirement: Caps count attempts, not successes

`client.request_count` SHALL equal attempts actually sent —
failures included — and `_check_caps()` SHALL raise
`AIRequestCapReached` BEFORE any send that would exceed a cap.

#### Scenario: Failed attempts consume the cap

- **WHEN** a run sends 5 attempts, 3 of which error
- **THEN** `request_count` is 5 and the cap treats all 5 as
  consumed

### Requirement: Every attempt is logged

Each send — success, error, or blocked — SHALL persist one
`AIRequest` row (job, role, requested model, attempt number,
status, latency, prompt sha256, options, token counts, cost)
and one `ai_providers` logger line. Image bytes are never
stored; `options['images']` records sha256/mime/bytes.

#### Scenario: Adapter raises mid-attempt

- **WHEN** `adapter.generate()` raises an `AIError`
- **THEN** an `AIRequest` row with `status='error'`,
  `error_type`, and scrubbed `error_message` is saved before
  the retry/fallback logic continues

### Requirement: Ordered fallback with retries

`generate(prompt, role)` SHALL try the role's assignments in
priority order; a provider raising `AIProviderError` is marked
dead for the client's lifetime and skipped. Retryable errors
retry per `provider.max_retries` with exponential backoff
(±20% jitter, ≤60s). `json_mode` is sent only to models whose
`supports_json_mode` flag is set.

#### Scenario: No assignment for the role

- **WHEN** `generate()` is called for a role with no active
  assignment
- **THEN** `AIJobNotConfiguredError` is raised naming the
  missing AIJobModel inline location in admin

#### Scenario: All models fail

- **WHEN** every assignment fails or is skipped
- **THEN** `AIAllModelsFailedError` carrying `last_error` is
  raised and a warning-level Sentry event is emitted
  (`rate_limited` if the last error was an `AIRateLimitError`,
  else `provider_error`)

#### Scenario: Fallback model without json_mode

- **WHEN** `options.json_mode` is requested and a fallback
  assignment's model has `supports_json_mode=False`
- **THEN** that model receives the request without the
  json_mode option

### Requirement: get_job_client resolution

`get_job_client()` SHALL accept an `AIJobSpec` (ensured via
`ensure_job`), an `AIJob` (used as-is), or a slug string
(existing row, else ensured from an autodiscovered spec).
Slugs matching no row and no spec SHALL raise
`AIJobNotConfiguredError` — arbitrary slugs never auto-create
jobs.

#### Scenario: Unknown slug

- **WHEN** `get_job_client('no.such.job')` is called with no
  matching row or spec
- **THEN** `AIJobNotConfiguredError` is raised

### Requirement: Normalized prompt storage

Prompts SHALL be stored normalized: `AIPromptTemplate` (key +
sha256, a new version per text change) and `AIInput`
(deduped by sha256, only when `AIJob.store_inputs`);
`AIRequest.rendered_prompt()` rebuilds the exact prompt and
verifies its sha256.

#### Scenario: Prompt text changes between runs

- **WHEN** a prompt file's content is edited
- **THEN** the next `generate()` creates a new
  `AIPromptTemplate` row for the new sha256 instead of mutating
  the old version

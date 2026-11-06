# Spec Delta

## ADDED Requirements

### Requirement: Task creation after digest build

After `build_digest()` commits a `NewsDigest`, the system SHALL
insert one Google task on behalf of the configured user into the
configured Google task list. The task body SHALL contain a
`title` naming the digest date and `notes` linking to
`{GOOGLE_TASKS_LINK_BASE_URL}/news/<date>/` (defaults to
`BASE_URL`) plus the ranked headlines; it SHALL
NOT set a `due` field. The attempt SHALL run after the digest
transaction commits and MUST NOT run for a `dry_run` build.

#### Scenario: Digest build creates a task

- **WHEN** `build_news_digest` runs for a date with no prior
  `created` link row
- **THEN** `tasks().insert` is called once with the digest's
  title/notes and a link row records `status='created'` with the
  returned `task_id` and `task_list_id`

#### Scenario: Dry-run touches nothing remote

- **WHEN** `build_digest(dry_run=True)` runs
- **THEN** no Google API call is made and no link row is written

### Requirement: Task list resolution by title

The target Google task list SHALL be resolved by the
`GOOGLE_TASKS_LIST_TITLE` setting (default `'News'`): list the
user's task lists, match the title case-insensitively, and when
absent create it via `tasklists().insert`. The resolved opaque
`list_id` SHALL be stored on the link row for audit.

#### Scenario: News list auto-created on first run

- **WHEN** the user's Google account has no task list titled
  `News` and a digest task is created
- **THEN** a `News` task list is created via
  `tasklists().insert` and the task lands in it

#### Scenario: Existing list is reused

- **WHEN** a task list titled `News` (any casing) already exists
- **THEN** its `list_id` is used and no new list is created

### Requirement: Rebuild dedup via link model

`NewsDigestTask` SHALL be a `OneToOneField` to `NewsDigest`
(`db_table='news_digest_task'`) recording `task_id`,
`task_list_id`, `status` (`pending`/`created`/`failed`),
`error`, `created_at`, `updated_at`. Task creation SHALL be
attempted only when no link row with `status='created'` exists
for the digest, so `update_or_create` rebuilds, `--date`
backfills and `top_n` changes never produce a second task. A
`failed` row MAY be retried on the next build.

#### Scenario: Rebuilt digest does not duplicate the task

- **WHEN** `build_news_digest` runs again for a date whose link
  row is `status='created'`
- **THEN** no `tasks().insert` call is made

#### Scenario: Failed attempt is retried once per build

- **WHEN** a previous build left `status='failed'` and the
  digest is rebuilt
- **THEN** one new insert attempt runs and the row's
  status/error is updated

### Requirement: Best-effort failure handling

The task-creation step SHALL catch every exception (missing or
revoked credentials, Google API errors, transport failures) —
it MUST NOT propagate into `build_digest()` or fail the
management command. Failures SHALL be logged through the `news`
logger and recorded on the link row as `status='failed'` with
the exception text in `error`. When credentials are missing the
log line SHALL point at `{BASE_URL}/google/login` as the re-auth
path.

#### Scenario: No Google credentials still yields a digest

- **WHEN** a digest builds while the configured user has no
  `GoogleOAuthCredentials` row
- **THEN** the digest and its items persist, a warning naming
  `/google/login` is logged, and the link row is `failed`

### Requirement: Feature toggle by configuration

The integration SHALL be active only when
`GOOGLE_OAUTH_CLIENT_JSON` and `GOOGLE_TASKS_USERNAME` are both
set; otherwise `build_digest()` SHALL behave exactly as before
(no link row, no API call, no log noise). `GOOGLE_TASKS_USERNAME`
SHALL name the Django `User` whose Google credentials are used;
a non-existent username SHALL be treated like missing
credentials (logged, `failed` link row).

#### Scenario: Unconfigured install is a no-op

- **WHEN** the new settings are unset and a digest builds
- **THEN** no link row is created and the digest flow is
  unchanged

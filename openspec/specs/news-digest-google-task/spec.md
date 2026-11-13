# news-digest-google-task Specification

## Purpose
Automatic creation of one Google task per built `NewsDigest`:
how the task content, target task list and the
`NewsDigestTask` link row keep rebuilds idempotent, and how
failures are recorded without ever blocking the digest
build.

## Requirements

### Requirement: Per-subscriber task fan-out

After `build_digest()` commits a `NewsDigest`, the system SHALL
insert one Google task per enabled `NewsDigestSubscription`
into each subscriber's own Google task list, acting as that
subscriber. The attempt SHALL run after the digest
transaction commits and MUST NOT run for a `dry_run` build.

#### Scenario: Digest build creates a task

- **WHEN** `build_news_digest` runs for a date and two users
  have enabled subscriptions
- **THEN** `tasks().insert` is called once per subscriber —
  each with that user's own credentials — and each
  `(digest, user)` link row records `status='created'` with
  the returned `task_id` and `task_list_id`

#### Scenario: No subscribers touches nothing remote

- **WHEN** a digest builds with zero enabled subscriptions
- **THEN** no Google API call is made and no link row is
  written

#### Scenario: Dry-run touches nothing remote

- **WHEN** `build_digest(dry_run=True)` runs
- **THEN** no Google API call is made and no link row is
  written

### Requirement: Task body content

The task body SHALL contain a `title` naming the digest date
and `notes` linking to
`{GOOGLE_TASKS_LINK_BASE_URL}/news/<date>/` (defaults to
`BASE_URL`) followed by one `- {headline} — {outlet name} —
{article link}` bullet per item; it SHALL NOT set a `due`
field. When the digest has no items the system SHALL skip the
subscriber entirely — no Google API call, no link row — so a
rebuild with items still creates the task fresh.

#### Scenario: Headlines use the subscriber's own ranking

- **WHEN** a story was covered by outlets A and B and the
  subscriber's `NewsSourcePreference` ranks B first
- **THEN** their task's notes carry B's outlet name and
  article link, not A's

#### Scenario: Story without a covering article

- **WHEN** a digest item's story has no confirmed member
  article
- **THEN** its bullet is a bare `- {headline}` with no
  outlet/link separators

#### Scenario: Empty digest creates no task

- **WHEN** a digest builds with zero items
- **THEN** no Google API call is made and no `NewsDigestTask`
  row is written for any subscriber

### Requirement: Task list resolution by title

Each subscriber's target Google task list SHALL be resolved
by the `GOOGLE_TASKS_LIST_TITLE` setting (default `'News'`):
list that user's task lists, match the title
case-insensitively, and when absent create it via
`tasklists().insert` on their account. The resolved opaque
`list_id` SHALL be stored on the user's link row for audit.

#### Scenario: News list auto-created on first run

- **WHEN** a subscriber's Google account has no task list
  titled `News` and a digest task is created for them
- **THEN** a `News` task list is created via
  `tasklists().insert` in their account and their task lands
  in it

#### Scenario: Existing list is reused

- **WHEN** a task list titled `News` (any casing) already
  exists in the subscriber's account
- **THEN** its `list_id` is used and no new list is created

### Requirement: Digest-task link model

`NewsDigestTask` SHALL be a `ForeignKey` to `NewsDigest`
(`related_name='google_tasks'`) plus a non-null `user` FK —
`db_table='news_digest_task'`,
`unique_together(digest, user)` — recording `task_id`,
`task_list_id`, `status` (`pending`/`created`/`failed`),
`error`, `created_at`, `updated_at`.

#### Scenario: Link rows are per (digest, user)

- **WHEN** two subscribers each receive a task for the same
  digest
- **THEN** two `NewsDigestTask` rows exist — one per user —
  and a second `(digest, user)` pair cannot be written

### Requirement: Rebuild dedup via link row

A link row with `status='created'` carrying
`task_id`/`task_list_id` SHALL make a rebuild refresh the
stored Google task in place via `tasks().patch` — a partial
update that preserves subscriber-set fields such as
`status` and `due` — never a second `tasks().insert` for
that subscriber — so the notes always reflect the current
items. A `failed`/`pending` row MAY be retried via insert.

#### Scenario: Rebuilt digest updates the task in place

- **WHEN** `build_news_digest` runs again for a date whose
  link row for a subscriber is `status='created'` with a
  stored `task_id`/`task_list_id`
- **THEN** `tasks().patch` refreshes that task's title and
  notes and no `tasks().insert` call is made for that user

#### Scenario: Rebuild serves newly subscribed users

- **WHEN** a digest already built has a `created` link row
  for user A, user B subscribes, and
  `build_news_digest --date <that date>` reruns
- **THEN** no insert runs for A but one runs for B, whose
  link row records `created`

#### Scenario: Failed attempt is retried once per build

- **WHEN** a previous build left a subscriber's link row at
  `status='failed'` and the digest is rebuilt
- **THEN** one new insert attempt runs for that user and the
  row's status/error is updated

### Requirement: In-place refresh failure handling

A `tasks().patch` 404 (the subscriber deleted the task)
SHALL fall back to `tasks().insert`, storing the new
`task_id` on the same row. Any other `tasks().patch`
failure SHALL keep the row at `status='created'` with its
`task_id` and record the error — the remote task may still
exist — so the next build retries the patch rather than
inserting a duplicate task.

#### Scenario: Deleted task is re-inserted

- **WHEN** the in-place `tasks().patch` gets a 404 because
  the subscriber deleted the Google task
- **THEN** the system falls back to `tasks().insert` and the
  same link row stores the new `task_id`

#### Scenario: Patch failure keeps the row retryable

- **WHEN** the in-place `tasks().patch` raises any error
  other than a 404
- **THEN** the link row stays `status='created'` with its
  `task_id` preserved and the error recorded, and the next
  build retries `tasks().patch` instead of inserting

### Requirement: Per-subscriber failure isolation

A missing grant, revoked credentials, Google API error or
transport failure for one subscriber MUST NOT abort or affect
the other subscribers' attempts, MUST NOT propagate into
`build_digest()` and MUST NOT fail the management command.

#### Scenario: Insert exception records only that user

- **WHEN** `tasks().insert` raises for subscriber A mid
  fan-out
- **THEN** A's link row is `failed` with the exception text,
  remaining subscribers are still attempted, and
  `build_digest()` returns normally

### Requirement: Failure audit on the link row

Each per-subscriber failure SHALL be logged through the
`news` logger and recorded on that user's link row with the
exception text in `error` — `status='failed'` for a
non-`created` row, while a `created` row keeps its status
and `task_id` (the remote task may still exist) so the next
build retries the in-place refresh rather than inserting a
duplicate. When credentials are missing the log line and
`error` SHALL point at `{BASE_URL}/google/login` as the
re-auth path.

#### Scenario: No Google credentials still yields a digest

- **WHEN** a digest builds while subscriber A's credential
  resolution returns `None` and subscriber B's grant is
  usable
- **THEN** A's link row is `failed` with a `/google/login`
  pointer, B's task is still inserted, and the digest and
  its items persist unchanged

### Requirement: Feature toggle by configuration

The integration SHALL be active only when
`GOOGLE_OAUTH_CLIENT_JSON` is set; otherwise `build_digest()`
SHALL behave exactly as before (no link row, no API call, no
log noise). The `GOOGLE_TASKS_USERNAME` setting SHALL be
removed — recipients come exclusively from enabled
`NewsDigestSubscription` rows, so a configured install with
zero subscribers also makes no API calls and writes no link
rows.

#### Scenario: Unconfigured install is a no-op

- **WHEN** `GOOGLE_OAUTH_CLIENT_JSON` is unset and a digest
  builds
- **THEN** no link row is created and the digest flow is
  unchanged

#### Scenario: Configured install with no subscribers

- **WHEN** `GOOGLE_OAUTH_CLIENT_JSON` is set, no enabled
  subscriptions exist and a digest builds
- **THEN** no Google API call is made and no link row is
  written

### Requirement: Digest-task subscription opt-in

The system SHALL record at most one `NewsDigestSubscription`
row per user (`db_table='news_digest_subscription'`,
`is_enabled`, timestamps, admin-registered) as the opt-in to
receiving digest tasks. Subscribing SHALL create or
re-enable the caller's row; unsubscribing SHALL set
`is_enabled=False` while preserving the row and all
`NewsDigestTask` audit rows. Only enabled subscriptions
receive tasks, and deleting the user SHALL cascade their
subscription and link rows.

#### Scenario: Subscribe then unsubscribe

- **WHEN** a user subscribes, then unsubscribes
- **THEN** their subscription row still exists with
  `is_enabled=False`, prior `NewsDigestTask` rows are kept,
  and subsequent builds create no task for them

#### Scenario: Re-subscribe re-enables

- **WHEN** a previously unsubscribed user subscribes again
- **THEN** the same row flips to `is_enabled=True` — no
  second row exists

### Requirement: Digest-task status endpoint

`GET /api/news/digest-task/` SHALL require an authenticated
session and answer `{oauth_configured, google_connected,
subscribed, last_task}`: `oauth_configured` reflects
`GOOGLE_OAUTH_CLIENT_JSON`, `google_connected` reflects a
stored `GoogleOAuthCredentials` row covering the tasks scope
(no token refresh attempted on read), `subscribed` reflects
an enabled subscription, and `last_task` is the caller's
newest `NewsDigestTask` (`{digest_date, status, error,
updated_at}`) or `null`.

#### Scenario: Anonymous caller

- **WHEN** an anonymous request hits the endpoint
- **THEN** the response is the standard 401 `login_url`
  handshake pointing at `/news/preferences/`

#### Scenario: Subscriber with a failed last task

- **WHEN** a subscribed user whose last link row is `failed`
  GETs the endpoint
- **THEN** the response carries `subscribed: true` and
  `last_task.status: 'failed'` with the recorded `error`

### Requirement: Digest-task subscribe and unsubscribe ops

`POST /api/news/digest-task/subscribe/` and
`POST /api/news/digest-task/unsubscribe/` SHALL require an
authenticated session (CSRF enforced), act idempotently on
the caller's subscription row, and answer 200 with the same
status payload as the GET. Subscribing without a Google
grant SHALL still succeed — 200 with
`google_connected: false` — leaving connection to
`/google/login`; any authenticated user MAY subscribe
regardless of staff status.

#### Scenario: Subscribe before connecting Google

- **WHEN** a user with no `GoogleOAuthCredentials` row POSTs
  to subscribe
- **THEN** the response is 200 with `subscribed: true` and
  `google_connected: false` — no 4xx

#### Scenario: Unsubscribe is idempotent

- **WHEN** a user with no subscription POSTs to unsubscribe
- **THEN** the response is 200 with `subscribed: false`

### Requirement: Digest-task card on the preferences page

The `/news/preferences/` SPA page SHALL render a Google
Tasks digest card driven by the status endpoint, mapping
each state to one action — hidden, Connect, Subscribe, or
Unsubscribe — and SHALL carry subscribe intent through the
OAuth return so the page auto-subscribes on landing.

#### Scenario: Card hidden when OAuth is unconfigured

- **WHEN** the status endpoint reports
  `oauth_configured: false`
- **THEN** the card does not render

#### Scenario: Connect round-trip lands subscribed

- **WHEN** a connected-less user clicks Connect Google,
  consents, and returns to `/news/preferences/?subscribe=1`
- **THEN** the page fires the subscribe op once and renders
  the subscribed state

#### Scenario: Subscribed card surfaces last failure

- **WHEN** a subscribed user's `last_task.status` is
  `failed`
- **THEN** the card shows the error with a re-connect hint
  pointing at `/google/login`

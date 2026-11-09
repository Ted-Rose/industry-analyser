# Design

## Context

`news/tasks.py` today resolves a single `User` via
`settings.GOOGLE_TASKS_USERNAME` and inserts one Google task
per `NewsDigest`, deduped by the `NewsDigestTask` link row
(`OneToOneField` on digest). The OAuth flow in `google_api`
already stores per-user credentials for any logged-in user
and `get_user_credentials(user, scopes)` refreshes them.
`news/preferences.py`'s `ordered_story_articles(story, user)`
is already user-aware — each subscriber's task notes can
rank outlets by their own `NewsSourcePreference` rows for
free. The `/news/preferences/` SPA page is the app's only
authenticated surface, which makes it the natural home for
the subscription UI.

## Goals / Non-Goals

**Goals:**

- Any registered user can connect Google and opt into
  digest tasks with at most one click after returning from
  OAuth.
- Per-(digest, user) link rows keep rebuild dedup and give
  every subscriber an audit trail.
- One subscriber's failure (no grant, revoked token, API
  error) is invisible to the others.
- No settings a deploy must learn: subscriptions, not env
  vars, pick recipients.

**Non-Goals:**

- Changing the OAuth flow, scopes (`auth/tasks` stays the
  only scope) or the `google_api` credential lifecycle.
- Immediate task backfill for digests built before a user
  subscribed (see Decisions — `--date` rerun covers it).
- Per-subscriber task-list titles or digest content
  customization beyond the existing per-user outlet
  ranking.
- Deleting Google-side tasks on unsubscribe or when a
  digest is rebuilt.

## Decisions

### 1. `NewsDigestSubscription` — OneToOne opt-in row

`user` `OneToOneField` (CASCADE), `is_enabled` (default
`True`), `created_at`/`updated_at`,
`db_table='news_digest_subscription'`. OneToOne over
FK+unique because one row per user is the whole shape — it
matches `GoogleOAuthCredentials` and keeps lookups trivial.
`is_enabled` (rather than row-exists = subscribed) makes
unsubscribe a flip, keeping idempotent POST semantics and
preserving the row for re-subscribe and admin audit.
Alternative considered: delete the row on unsubscribe —
rejected, it conflates "never subscribed" with "opted out"
and loses the timestamps.

### 2. `NewsDigestTask` becomes per-(digest, user)

`digest` `OneToOneField` → `ForeignKey`
(`related_name='google_tasks'` — plural; verified only
`models.py` declares the singular name, nothing reads it),
new non-null `user` FK (CASCADE),
`unique_together(('digest', 'user'),)`, `db_table`
unchanged. Migration is three ops in one file:
add `user` nullable → `RunPython` backfill → `AlterField`
to non-null. Backfill rule: when exactly one
`GoogleOAuthCredentials` row exists (the prod reality — the
maintainer), assign it; else the first superuser by pk;
else delete the orphaned audit rows. Rationale: legacy rows
were provably created for the one configured user, and the
rows are audit-only, so a deterministic fallback beats
leaving them ambiguous. The migration reads no env var —
`GOOGLE_TASKS_USERNAME` may already be gone from settings.

### 3. Fan-out inside `create_digest_task`

The function iterates enabled subscriptions
(`select_related('user')`); per subscriber: skip when a
`created` link row exists → `update_or_create` the
`(digest, user)` row to `pending` → resolve creds (missing
→ `failed` row whose error names `/google/login`) → build
service → resolve task list → insert → `created`. A
per-subscriber `try/except` records `failed` and continues;
the existing outer catch still guarantees the call never
raises into `build_digest()`. Alternative: a Django-Q /
async fan-out — rejected, there is no worker tier and
subscriber counts are small; sequential Google calls inside
the daily job are fine (already outside the digest
transaction).

### 4. `GOOGLE_TASKS_USERNAME` is removed, not deprecated

`_feature_enabled()` collapses to the
`GOOGLE_OAUTH_CLIENT_JSON` check; the setting, its
`settings.py` comment and `.env.example` line are deleted.
Rationale: a silently ignored env var is a worse trap than
a clean removal, and the maintainer keeps receiving tasks
by subscribing like everyone else (they already hold the
only `GoogleOAuthCredentials` row). Leftover prod env
values are harmless.

### 5. Subscribe succeeds without a Google grant (200, flag)

`POST /subscribe/` upserts `is_enabled=True` and returns
200 `{…, google_connected: false}` instead of 409.
Rationale: the subscription is meaningful on its own — the
user can connect Google afterwards and the next build just
works; a `failed` link row with a `/google/login` pointer
already models the gap. A 409 would force the SPA into an
error path for a perfectly recoverable ordering.
Alternative: server-side auto-redirect to `/google/login` —
rejected, JSON ops shouldn't drive navigations; the SPA
owns that flow via `next`.

### 6. `google_connected` is a cheap DB check, not a refresh

The status endpoint reports
`GoogleOAuthCredentials` row-exists + `has_all_scopes`
rather than calling `get_user_credentials`, which may fire
a network token-refresh inside a GET. A revoked grant can't
be detected without a Google call anyway — it surfaces the
next build as a `failed` `last_task`, which the card shows.

### 7. Auto-subscribe after OAuth via `?subscribe=1`

When the card's Connect action fires while
`google_connected` is false, it navigates to
`/google/login/?next=/news/preferences/?subscribe=1`.
`login_view` stores `next` verbatim in the session
(`oauth_redirect_url`) and the callback redirects there —
verified in `google_api/views.py` — so the query param
survives the round-trip with zero backend changes. On
landing, `Preferences.tsx` reads the param, fires subscribe
once (guarded by `google_connected && !subscribed`), then
strips it via `setSearchParams(..., {replace: true})`.
Alternative: explicit second click after return — simpler
code, worse UX (users reliably forget the second step).
Alternative: a `pending_subscribe` session flag — equal UX
but adds backend state for no benefit. Trade-off accepted:
a refreshed `?subscribe=1` URL could re-subscribe someone
who just unsubscribed — mitigated by the guard and the
param strip; both are one extra click to undo.

### 8. Next-build-only for new subscribers

Subscribing creates no task for already-built digests;
tasks start with the next `build_news_digest` run.
Rationale: an inline "create my task now" call inside the
subscribe POST adds remote-call latency/failure semantics
to a settings endpoint, and the maintainer can already
backfill any date with `build_news_digest --date <d>` —
per-user dedup means the rerun only inserts for users
lacking a `created` row. Documented as accepted UX cost:
a user subscribing today sees their first task tomorrow
(or after a manual rerun).

### 9. `SPA_SUBPATHS` gains a `digest-task` entry

`('news', 'digest-task') → '/news/preferences/'` so the 401
`login_url` handshake for the new ops lands on the page
that owns the card (the mechanical rewrite would emit
`/news/digest-task/`, which the news router's `*` route
silently redirects to `/` — a login round-trip would lose
the user entirely).

### 10. Admin surface

`NewsDigestSubscriptionAdmin`: `list_display = ('user',
'is_enabled', 'updated_at')`, `list_editable` is_enabled so
staff can opt a user out. `NewsDigestTaskAdmin` gains
`'user'` in `list_display`/`readonly_fields` — stays
read-only audit.

## Risks / Trade-offs

- [Subscribed-but-never-connected users accumulate a
  `failed` link row per daily build] → Accepted: the row is
  the audit trail and its error points at `/google/login`;
  the status endpoint surfaces it on the card so the user
  can self-fix. No log noise beyond one warning per user
  per build.
- [Revoked grants fail silently until the daily build] →
  The card shows `last_task.status='failed'` + error with a
  re-connect hint; no active notification (out of scope).
- [Migration runs manually on prod] → Per repo convention
  the maintainer applies it; the backfill is deterministic
  for the single-OAuth-user prod reality. Rollback is the
  reverse migration (drops `user` + the subscription table
  — audit data loss is inherent, noted not solved).
- [Sequential Google calls per subscriber slow the digest
  job] → Bounded by subscriber count; each call is one
  tasklists.list (+maybe insert) + one tasks.insert.
  `GOOGLE_TASKS_LIST_TITLE` is shared, so a renamed list
  auto-creates per subscriber as before.
- [Card lives on `/news/preferences/`] → Users who never
  visit preferences never discover it; acceptable — it's
  the app's only authed page and where outlet ranking
  already lives.

## Migration Plan

1. Ship the `news` migration file (subscription table +
   `NewsDigestTask` reshape + backfill) in the same commit
   as the code.
2. Deploy; maintainer applies `python manage.py migrate`
   manually against prod per repo convention — code is
   forward-only (old code tolerates the new schema only
   until it needs `google_task`; deploy order: migrate
   first, then new code, matching how this repo ships
   schema changes).
3. Post-deploy: maintainer visits `/news/preferences/`,
   connects Google if needed (already connected), clicks
   Subscribe. `GOOGLE_TASKS_USERNAME` may be dropped from
   prod env at leisure — it becomes a no-op.

## Open Questions

- None blocking. Nice-to-have later: surface a
  connect/subscribe hint on the public digest pages so
  users discover the feature without visiting
  `/news/preferences/` first.

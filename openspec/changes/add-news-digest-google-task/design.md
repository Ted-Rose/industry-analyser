# Design

## Context

`build_digest()` (`news/digest.py:58-120`) is the single write path
for `NewsDigest` — invoked by the `build_news_digest` management
command, which `run_all_jobs` schedules as `local:daily`: it runs
only on the maintainer's machine, never on Cloud Run
(`scrape_jobs/management/commands/run_all_jobs.py:64`). The command
writes to production Postgres via `.env`'s `DATABASE_URL`.

The sibling project `django-apps` already implements this exact
pattern and is the port source:

- `google_api/models.py` — `GoogleOAuthCredentials` (51 lines)
- `google_api/utils.py` — `get_user_credentials` (280-423),
  `google_auth` (426-559), `callback` (579-713),
  `build_google_service` (562-576), env hacks (43-47)
- `google_tasks/services.py` — `create_task` (740-821)

Its HTTP API is unusable here: session `django_auth` + CSRF only,
no API-key/bearer auth anywhere, `CORS_ALLOW_CREDENTIALS` unset,
and credentials are keyed to *its* `User` rows. The trigger is a
management command anyway — there is no session to call it with.

## Goals / Non-Goals

**Goals:**

- One Google task per `NewsDigest`, created automatically at build
  time, deduplicated across rebuilds.
- Google OAuth credential lifecycle reusable by future features
  (platform app, not news-specific).
- Zero coupling to `django-apps` at runtime — shared code only.

**Non-Goals:**

- No `due` date on the task (explicit product decision).
- No bidirectional sync — the task is fire-and-forget; completing
  or editing it in Google Tasks never writes back.
- No Google sign-in — login stays Django-session; OAuth only
  attaches credentials to an authenticated user.
- No frontend/SPA work; admin gets a read-only link-model view.

## Decisions

### 1. Port code, don't call the django-apps API

Alternatives considered: (a) call `POST /api/tasks/task/create/`
on django-apps — rejected: session+CSRF auth, no credentials
cross-origin, foreign `User` keying, and no session context in a
management command; (b) Google service account — rejected: Tasks
API has no service-account path into a normal user's lists.
Porting ~400 lines is the only viable path.

### 2. New `google_api` platform app (mirror of django-apps')

Keeps Google auth reusable for future features and makes the port
a near-verbatim copy:

| Source (django-apps) | Target | Change |
|---|---|---|
| `google_api/models.py` | `google_api/models.py` | Verbatim + `db_table` |
| `utils.py` env hacks 43-47 | `google_api/utils.py` top | Verbatim |
| `utils.py` `get_user_credentials` | same | Verbatim — **keep naive-UTC↔aware conversions** |
| `utils.py` `google_auth` | same | Drop legacy session-dict branch; keep DB path + `{authorization_url, state, scopes}` return |
| `utils.py` `build_google_service` | same | Verbatim |
| `utils.py` `callback` | `google_api/views.py` | `@login_required`, `request.user`; drop userinfo→User creation; keep `update_or_create` |
| `views.py` `login_view` | `google_api/views.py` | Scope = `auth/tasks` only |
| `google_api/urls.py` | `google_api/urls.py` | `login/` + `google/callback` |

Mount under `path('google/', include('google_api.urls'))` in
`industry_analyser/urls.py`, before the terminal SPA catch-all.

### 3. Explicit call in `build_digest`, not a `post_save` signal

`NewsDigest` is written by `update_or_create`, so `post_save`
fires on every rebuild — signals would need dedup anyway. The
project uses zero signals; explicit service calls are the
convention. Insert after the `transaction.atomic()` block:

```python
if not dry_run:
    with transaction.atomic():
        ...  # existing digest write
    from news.tasks import create_digest_task  # or top-level
    create_digest_task(digest)                  # never raises
```

Outside the atomic block so a slow Google call never holds the
transaction open, and skipped naturally by `dry_run`.

### 4. `NewsDigestTask` link model for dedup + audit

`OneToOneField(NewsDigest)`, fields `task_id`, `task_list_id`,
`status` (`pending`/`created`/`failed`), `error`, timestamps.
Creation is attempted only when no `status='created'` row exists;
`failed` rows retry on next build. One link row per digest keeps
rebuilds idempotent — matching the digest's own
`update_or_create` contract.

### 5. Task list resolved by title, auto-created

`GOOGLE_TASKS_LIST_TITLE` (default `'News'`) →
`service.tasklists().list()` → case-insensitive title match →
`tasklists().insert(body={'title': ...})` when absent (the API
supports it; django-apps just never needed it). Re-resolved each
run — one extra list call per day is negligible and survives the
user renaming/deleting lists in Google.

### 6. Task content: title + notes, no `due`

Title: `News digest {date.isoformat()}`. Notes: link
`{BASE_URL}/news/{date}/` plus ranked headlines
(`{rank}. {headline}` lines). No `due` field — user's call. An
empty digest still gets a task: the `NewsDigest` row exists, and
"nothing happened today" is still worth a glance.

### 7. Configuration follows existing env conventions

- `GOOGLE_OAUTH_CLIENT_JSON` → materialize to a file at settings
  import, expose `GOOGLE_APP_SECRETS_PATH` (django-apps pattern;
  `env-file` secret delivers it on Cloud Run).
- `GOOGLE_TASKS_LIST_TITLE` (default `'News'`),
  `GOOGLE_TASKS_USERNAME` — feature is active only when
  `GOOGLE_OAUTH_CLIENT_JSON` **and** `GOOGLE_TASKS_USERNAME` are
  set; empty = disabled, same convention as `GCS_AUDIO_BUCKET`.
- `redirect_uri = {BASE_URL}/google/callback` — `BASE_URL`
  already exists; must match a registered URI (dev.sh serves on
  8274, so local `.env` needs `BASE_URL=http://127.0.0.1:8274`
  or the loopback port must be registered).

### 8. Reuse the existing OAuth client

Add industry-analyser's `/google/callback` URIs to the OAuth
client in GCP project `django-apps-7345` and enable the Tasks API
there. Alternative — a new OAuth client in
`gen-lang-client-0833674612` — means a fresh consent screen stuck
in Testing mode, capping refresh tokens at 7 days; the existing
client already covers `auth/tasks`. Both are manual GCP Console
steps, not terraform.

## Risks / Trade-offs

- [7-day refresh token expiry] → only if the consent screen is in
  Testing mode; reusing the django-apps-7345 client (already
  consented for `auth/tasks`) avoids it. If the grant still
  expires, `/google/login` re-consent is one click.
- [Naive vs aware datetime bug on token expiry] → port
  `get_user_credentials` verbatim including conversions; tests
  cover the expired-token path.
- [Job is local-only, failures invisible] → link row `status` +
  `error` give an audit trail in admin; `news` logger writes to
  `logs/`; Sentry egress is broken locally anyway (Netskope).
- [Wrong `GOOGLE_TASKS_USERNAME`] → treated as missing creds:
  logged warning + `failed` row, digest unaffected.
- [Secret leakage] → `GOOGLE_OAUTH_CLIENT_JSON` lives in `.env` /
  `env-file` secret only; admin and logs must never print tokens;
  `.env.example` documents names without values.
- [google-auth imported but unpinned] → it arrives transitively
  today; pin it explicitly since we import it directly.

## Migration Plan

1. Land code + both migrations; `python manage.py check`;
   `DATABASE_URL=sqlite:///db.sqlite3 python manage.py migrate`
   locally and for tests.
2. GCP Console: enable Google Tasks API on `django-apps-7345`;
   add `{prod BASE_URL}/google/callback` and
   `http://127.0.0.1:8274/google/callback` to the OAuth client's
   redirect URIs.
3. `.env`: add `GOOGLE_OAUTH_CLIENT_JSON`, `GOOGLE_TASKS_USERNAME`,
   `BASE_URL` override if needed. Add to the `env-file` secret
   only if the web flow should also work on the prod site.
4. Maintainer applies prod migrations manually (no CI step —
   `.devin/rules/migrations.md`).
5. One-time: `/google/login` → consent → credentials row exists;
   next `build_news_digest` run creates the first task.
6. Rollback: unset `GOOGLE_TASKS_USERNAME` — feature no-ops with
   code in place; models can be dropped in a later migration.

## Open Questions

None blocking. Worth confirming at implementation time: the exact
username value for `GOOGLE_TASKS_USERNAME` (query
`User.objects.values_list('username', flat=True)` against the
read-only `ai_agent` prod DB before writing `.env`).

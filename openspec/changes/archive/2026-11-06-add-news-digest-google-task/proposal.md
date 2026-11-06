# Proposal

## Why

When the daily news digest is built there is no external reminder
that fresh news is waiting. The owner already lives in Google Tasks;
creating a task per digest turns "check the news page" into a normal
part of their task workflow. The sibling project `django-apps`
proved the pattern (per-user Google OAuth credentials + Tasks API)
but its HTTP API is session-only and keyed to its own `User` table,
so the integration must be built in this repo, not called remotely.

## What Changes

- New `google_api` platform app: `GoogleOAuthCredentials` model
  (per-user access/refresh tokens, expiry, scopes), credential
  load/refresh helpers, and a Google OAuth web flow
  (`/google/login` + `/google/callback`) that attaches granted
  credentials to the logged-in Django user.
- New `NewsDigestTask` link model in `news/`: one row per
  `NewsDigest`, recording the created Google task id, task list id,
  and status (`pending`/`created`/`failed`) for dedup and audit.
- `build_digest()` gains a best-effort post-commit step that creates
  a Google task for the digest: title + notes (link + headlines),
  **no due date**, inserted into a task list resolved by configured
  title (default `"News"`), auto-created via `tasklists().insert`
  when absent. Failures are logged and recorded on the link row;
  they never fail the digest build.
- New settings: `GOOGLE_OAUTH_CLIENT_JSON` (client secrets
  document), `GOOGLE_TASKS_LIST_TITLE`, `GOOGLE_TASKS_USERNAME`.
  Empty/unset disables the feature (same convention as
  `GCS_AUDIO_BUCKET`).
- New pinned deps: `google-api-python-client`,
  `google-auth-oauthlib` (`google-auth` already present).

## Capabilities

### New Capabilities

- `google-oauth`: Per-user Google OAuth2 credential lifecycle —
  storage, scope check, access-token refresh, and the web
  login/callback flow that populates credentials.
- `news-digest-google-task`: Automatic creation of a Google task in
  a configured Google task list when a `NewsDigest` is built,
  including task-list resolution/auto-creation, dedup across digest
  rebuilds, and failure handling that never blocks digest creation.

### Modified Capabilities

<!-- None: user-auth stays Django-session based; the OAuth callback
     attaches to an already-authenticated user rather than acting
     as a login mechanism. -->

## Impact

- **Code**: new `google_api/` app; `news/digest.py`,
  `news/models.py`, `news/admin.py`, `news/tasks.py` (new),
  `industry_analyser/settings.py`, `industry_analyser/urls.py`,
  `requirements.txt`, `.env.example`.
- **Migrations**: `google_api.0001`, `news.0004` — prod apply is
  manual per repo rules.
- **External**: Google Tasks API must be enabled on the OAuth
  client's GCP project; redirect URIs registered on the shared
  OAuth client (`django-apps-7345`); `auth/tasks` scope.
- **No API surface change** — no ninja endpoints added; the OAuth
  flow is plain Django views.
- **Layers impacted:** backend.

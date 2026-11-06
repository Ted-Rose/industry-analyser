# Spec Delta

## ADDED Requirements

### Requirement: Per-user Google credential storage

`GoogleOAuthCredentials` SHALL store one row per Django user:
`access_token`, `refresh_token`, `token_expiry` and granted
`scopes` (JSON list), with `db_table='google_oauth_credentials'`
and `user` as a unique `OneToOneField`. Token values MUST NOT be
exposed in admin list views, logs or API responses — the admin
registration shows user, expiry and scopes only.

#### Scenario: Re-consent replaces the stored grant

- **WHEN** a user completes the OAuth flow a second time
- **THEN** `update_or_create` overwrites the existing row —
  exactly one credentials row exists per user

### Requirement: Credential resolution and refresh

`get_user_credentials(user, scopes)` SHALL return
`google.oauth2.credentials.Credentials` built from the stored
row, refreshing via `refresh_token` when `token_expiry` has
passed and persisting the new token back to the row. It SHALL
return `None` — never raise — when no row exists, stored scopes
don't cover the request, or Google rejects the refresh.
Expiry values MUST convert between google-auth's naive-UTC and
Django's aware datetimes in both directions.

#### Scenario: Expired token refreshes transparently

- **WHEN** stored credentials' `token_expiry` is in the past and
  a `refresh_token` is present
- **THEN** the helper refreshes against Google, updates the row
  and returns usable `Credentials`

#### Scenario: Revoked grant signals re-auth

- **WHEN** Google answers the refresh with `RefreshError`
- **THEN** the helper returns `None` and the stored row is left
  unchanged for diagnostics

### Requirement: Google OAuth web flow

`GET /google/login` SHALL be `@login_required`, stash `state`
and a `next` path in the session, and redirect to Google's
consent screen (`access_type='offline'`, scope `auth/tasks`).
`GET /google/callback` SHALL be `@login_required`, exchange the
code, `update_or_create` the credentials row for
`request.user`, and redirect to `next`. `redirect_uri` SHALL be
`{BASE_URL}/google/callback`. The flow MUST NOT create or
re-authenticate Django users; denied grants redirect back to
`/google/login`.

#### Scenario: Owner connects their Google account

- **WHEN** a logged-in user visits `/google/login`, consents on
  Google and returns to `/google/callback`
- **THEN** a `GoogleOAuthCredentials` row exists for that user
  holding a refresh token and the `auth/tasks` scope

#### Scenario: Anonymous visitor is bounced to Django login

- **WHEN** an anonymous request hits `/google/login` or
  `/google/callback`
- **THEN** the response is the standard `login_required`
  redirect — no OAuth state is created

#### Scenario: User denies consent

- **WHEN** Google redirects back with an access-denied error
- **THEN** the user is redirected to `/google/login` and no
  credentials row is written

### Requirement: Client secrets configuration

The OAuth client secrets document SHALL be supplied via the
`GOOGLE_OAUTH_CLIENT_JSON` env var (the full `{"web": {...}}`
JSON), materialized to a file path exposed as
`GOOGLE_APP_SECRETS_PATH` at settings import — mirroring how the
`env-file` secret delivers it on Cloud Run. A missing or empty
`GOOGLE_OAUTH_CLIENT_JSON` SHALL disable the web flow cleanly:
`/google/login` answers 503 with a plain message instead of
raising `ImproperlyConfigured`.

#### Scenario: Unconfigured deploy degrades gracefully

- **WHEN** `GOOGLE_OAUTH_CLIENT_JSON` is unset and a logged-in
  user visits `/google/login`
- **THEN** the response is a 503 explaining Google OAuth is not
  configured, not a 500

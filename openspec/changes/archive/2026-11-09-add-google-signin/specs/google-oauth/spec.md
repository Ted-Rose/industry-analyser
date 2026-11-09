# Spec Delta

## MODIFIED Requirements

### Requirement: Per-user Google credential storage

`GoogleOAuthCredentials` SHALL store one row per Django user:
`access_token`, `refresh_token`, `token_expiry`, granted
`scopes` (JSON list) and `google_sub` (unique, nullable —
the OIDC subject of the linked Google identity), with
`db_table='google_oauth_credentials'` and `user` as a unique
`OneToOneField`. Token values MUST NOT be exposed in admin
list views, logs or API responses — the admin registration
shows user, `google_sub`, expiry and scopes only.

#### Scenario: Re-consent replaces the stored grant

- **WHEN** a user completes the OAuth flow a second time
- **THEN** `update_or_create` overwrites the existing row —
  exactly one credentials row exists per user

#### Scenario: Legacy rows keep a null google_sub

- **WHEN** a row predates `google_sub` and its owner
  re-completes either OAuth mode
- **THEN** the row's `google_sub` is populated on the next
  `update_or_create` whenever the granted scopes allow a
  userinfo call — always in sign-in mode, but best-effort in
  connect mode: a tasks-only grant cannot read userinfo, so
  `google_sub` stays null there — no separate backfill is
  required

### Requirement: Google OAuth web flow

`GET /google/login` SHALL stay `@login_required`, stash mode
`connect`, `state` and a sanitized `next`, and redirect to
Google's consent screen (scope `auth/tasks`).
`GET /google/callback` SHALL verify `state` matches the
session's before token exchange, then dispatch on the
stashed mode (absent → `connect`): connect requires an
authenticated caller (anonymous → `login_required` bounce)
and `update_or_create`s `request.user`'s row.
`redirect_uri` SHALL be `{BASE_URL}/google/callback`.

#### Scenario: Owner connects their Google account

- **WHEN** a logged-in user visits `/google/login`, consents
  on Google and returns to `/google/callback`
- **THEN** a `GoogleOAuthCredentials` row exists for that
  user holding a refresh token and the `auth/tasks` scope

#### Scenario: Anonymous visitor is bounced to Django login

- **WHEN** an anonymous request hits `/google/login`, or
  `/google/callback` with flow mode `connect` (or no stashed
  mode)
- **THEN** the response is the standard `login_required`
  redirect — no OAuth state is created

#### Scenario: State mismatch aborts the exchange

- **WHEN** the callback's `state` query param does not match
  the session-stashed value
- **THEN** no token exchange runs, the session OAuth keys are
  discarded and the user is redirected to the mode's start
  point

#### Scenario: Callback without a stashed flow is rejected

- **WHEN** `/google/callback` is hit on a session that never
  started a flow — no session-stashed `state`, whether or not
  a `state` query param is present
- **THEN** it is treated as a state mismatch: no token
  exchange runs — "both sides empty" is not a match — and the
  session OAuth keys are discarded

#### Scenario: Non-local next is ignored

- **WHEN** `/google/login` or `/google/signin` is hit with a
  `next` that is absolute or protocol-relative
- **THEN** the session records `/` as the redirect target
  instead

#### Scenario: User denies consent

- **WHEN** Google redirects back with an access-denied error
  in connect mode
- **THEN** the user is redirected to `/google/login` and no
  credentials row is written

## ADDED Requirements

### Requirement: Sign-in OAuth mode

`GET /google/signin` SHALL request `openid`,
`userinfo.email` and `userinfo.profile`, adding `auth/tasks`
only when `?tasks=1`. After token exchange the callback
SHALL fetch the OIDC `userinfo` endpoint with the granted
access token and use its `sub`, `email` and `email_verified`
claims for resolution. `access_type='offline'` and
`include_granted_scopes='true'` SHALL apply, so the grant
doubles as the stored credential.

#### Scenario: tasks=1 defaults the landing to subscribe

- **WHEN** a sign-in starts with `?tasks=1` and no `next`
- **THEN** the stashed redirect target is
  `/news/preferences/?subscribe=1` and `next` alone defaults
  to `/`

#### Scenario: Checkbox grant covers digest tasks

- **WHEN** a visitor signs in via `/google/signin/?tasks=1`
  and grants every requested scope
- **THEN** their credentials row lists `auth/tasks` in
  `scopes` and `GET /api/news/digest-task/` reports
  `google_connected: true` — no second `/google/login`
  round-trip is needed

#### Scenario: Plain sign-in stores no tasks scope

- **WHEN** a visitor signs in via `/google/signin/` without
  `tasks=1`
- **THEN** their credentials row holds the sign-in scopes
  only, and digest-task status reports
  `google_connected: false`

#### Scenario: Incremental authorization preserves prior
  grants

- **WHEN** a user who previously granted `auth/tasks` signs
  in without `tasks=1`
- **THEN** `include_granted_scopes` keeps `auth/tasks` in the
  returned scopes and the stored row retains it

#### Scenario: Userinfo fetch failure is a clean restart

- **WHEN** the userinfo request fails or returns no `sub`
- **THEN** the user is redirected to `/accounts/login/`, no
  session is established and no credentials row is written

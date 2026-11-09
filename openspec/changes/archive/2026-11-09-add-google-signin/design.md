# Design

## Context

Credential registration and login already exist
(`POST /api/accounts/register|login/`,
`CaseInsensitiveAuthBackend`, the `/accounts/` SPA). The
`google_api` app already owns a per-user OAuth credential
store (`GoogleOAuthCredentials`) and a `/google/login` +
`/google/callback` web flow — but it is strictly an
attach-a-grant flow: `@login_required`, tasks scope only, and
it "must never create or re-authenticate Django users". The
news digest fan-out (`news/tasks.py`) reads the stored grant
per subscriber. No allauth/social-auth dependency exists;
`google-auth-oauthlib`'s `InstalledAppFlow` plus `requests`
are already pinned in both dependency files.

## Goals / Non-Goals

**Goals:**
- One-click "Sign in with Google" that creates a non-staff
  account on first use and logs in returning users.
- An opt-in checkbox on that same consent that also grants
  `auth/tasks`, so a new user can reach the digest-task
  subscribe flow without a second OAuth round-trip.
- Keep the existing connect flow (`/google/login`) working
  unchanged for already-logged-in users.

**Non-Goals:**
- No password reset / email verification flows (no email
  sending exists in the project; Google-only users who lose
  their Google access can't fall back to a password).
- No account-disconnect UI, no listing of linked providers
  beyond the existing digest-task status endpoint.
- No change to access tiers: Google users are regular
  non-staff accounts.
- No second OAuth client, no new redirect URIs, no new
  secrets.

## Decisions

### 1. One shared `/google/callback`, dispatched on a session
###    flow-mode key

The redirect URI `{BASE_URL}/google/callback` is already
registered on the shared `django-apps-7345` OAuth client; a
second URI would be a manual GCP change for zero gain.
`/google/signin/` stashes `oauth_flow='signin'` next to the
existing `state`/`oauth_scopes`/`oauth_code_verifier`/
`oauth_redirect_url` session keys; `/google/login` stashes
`oauth_flow='connect'`. The callback drops
`@login_required`, reads the mode (absent → `connect`), and
re-applies the auth check inside the connect branch so
anonymous hits still bounce to `LOGIN_URL`. This preserves
the existing scenario where an anonymous callback redirects
to `/accounts/login/`.

### 2. `google_sub` on the existing credentials row

Google's OIDC `sub` is the only stable identity (emails can
be reused/changed). Rather than a new SocialAccount table
for a single provider, `GoogleOAuthCredentials` gains
`google_sub CharField(max_length=255, unique=True,
null=True, blank=True)` — one migration, populated on the
next grant for legacy rows (no backfill: they re-consent
anyway when they first sign in or re-connect). Added to the
admin `_SAFE_FIELDS` (not a token, safe to show).

### 3. Resolution order: sub → verified email → create

- `google_sub` match wins — it is the durable link and
  survives email changes.
- Verified email match links the existing account: Google's
  `email_verified` proves control of that address, which is
  the same trust the app places in the email column. The
  match is `email__iexact` + `order_by('id').first()` —
  deterministic if a legacy duplicate ever exists.
- Otherwise create: `is_staff=False`,
  `set_unusable_password()`, email written only when
  verified. Username = email local-part sanitized to the
  `^\S+$` contract (whitespace removed, characters outside
  `[A-Za-z0-9@.+-_]` replaced with `-`, truncated to leave
  room for a `-N` suffix loop over iexact collisions);
  fallback `google-<sub[:16]>` when no email exists.
- If the resolved user differs from `request.user`, sign in
  as the resolved user — consent was just given for that
  identity. (A logged-in user who wants to attach Google to
  *their* account uses connect mode, not sign-in.)
- Edge: a verified-email match whose existing credentials
  row already holds a *different* `google_sub` — the row is
  overwritten (one row per user) and the rebinding is logged
  as a warning.

### 4. Scopes and the userinfo call

`GOOGLE_SIGNIN_SCOPES = ['openid',
'https://www.googleapis.com/auth/userinfo.email',
'https://www.googleapis.com/auth/userinfo.profile']` in
`google_api/utils.py` next to `GOOGLE_TASKS_SCOPES`; the
signin view appends `GOOGLE_TASKS_SCOPES` when `?tasks=1`.
`google_auth()`'s parameters are reused
(`access_type='offline'`, `include_granted_scopes='true'`,
`prompt='consent'`) so a refresh token is always stored and
prior grants survive — a sign-in grant doubles as the
connect grant. The callback fetches
`https://openidconnect.googleapis.com/v1/userinfo` via
`flow.authorized_session()` — no ID-token validation needed
because userinfo is a direct TLS call to Google with the
just-issued token.

### 5. Tasks-scope checkbox → `?tasks=1`

The checkbox is unchecked by default (least privilege —
granting tasks access is never implicit). It only rewrites
the sign-in link's query string; there is no separate
consent flow because `include_granted_scopes` already merges
grants server-side. When `tasks=1` is present and no `next`
was given, `next` defaults to
`/news/preferences/?subscribe=1` — the preferences page
already auto-subscribes on that flag, completing the
"grant → subscribe" path in one landing.

### 6. Security hardening applied to both modes

- **State check**: the callback compares `request.GET
  ['state']` with the session-stashed value before
  `fetch_token` — today it is stashed but never verified,
  leaving a login-CSRF-shaped gap (attacker-driven callback
  completing *their* flow on the victim's browser). Mismatch
  → discard session OAuth keys, redirect to the mode's
  start.
- **`next` sanitization**: only same-origin relative paths
  (`/` prefix, not `//`) are stashed — the current
  `request.GET.get('next', '/')` would let
  `/google/login?next=https://evil/` become an open
  redirect.
- CSRF on the API is unchanged (all OAuth endpoints are
  GETs); `auth_login()` rotates the session key so fixation
  is covered; tokens stay server-side in the existing table
  and never reach admin lists, logs or API responses.
- Secrets: `GOOGLE_OAUTH_CLIENT_JSON`/`GOOGLE_APP_SECRETS_PATH`
  delivery is unchanged (env / shared `env-file` secret) —
  nothing new is added to Secret Manager or code.

### 7. UI: bootstrap flag over a new API op

`google_oauth_configured`
(`bool(settings.GOOGLE_APP_SECRETS_PATH)`) is added to the
existing `bootstrap` dict in
`industry_analyser/views.py::_spa_shell_context` — every SPA
already reads it via `useBootstrap`, and `BootstrapPayload`'s
index signature tolerates the new key. This avoids a new
ninja op and an `openapi.json` regen for what is static
config. The Google section is a shared component inside
`frontend/src/accounts/` used by Login and Register; it is
an `<a>` link (OAuth needs a top-level navigation), not a
form post.

### 8. `/google` added to the service worker bypass

`sw.js` `BYPASS_PATHS` is `['/admin', '/api', '/accounts']`
— a cached navigation response could otherwise interfere
with the OAuth round-trip. `/google` joins the list and
`PWA_CACHE_VERSION` in `fetcher/views.py` is bumped.

## Assumptions

- "Google Tasks news creation" means the
  `https://www.googleapis.com/auth/tasks` scope already used
  by `news/tasks.py` (one task per digest per enabled
  `NewsDigestSubscription`). The checkbox only *grants* the
  scope; receiving tasks still requires subscribing on
  `/news/preferences/` — which is why the `tasks=1` default
  `next` lands there with `?subscribe=1`.
- Consumer/Workspace Google accounts return `email` +
  `email_verified` under the `userinfo.email` scope; the
  no-email fallback exists only for edge cases.
- Google-created users keep an unusable password forever;
  password reset is out of scope (no mail sender exists).

## Risks / Trade-offs

- [Account linking by verified email could surprise a user
  who registered with a password expecting a separate
  account] → Accepted: Google-verified email is a strong
  ownership proof; documented in the spec. Alternative —
  always creating a new user — would fragment identity and
  break digest subscriptions tied to the original account.
- [`prompt='consent'` forces the consent screen on every
  sign-in] → Deliberate: it guarantees a fresh
  `refresh_token` every time, matching today's connect flow.
  Revisit to `select_account` only if re-login UX matters.
- [OAuth consent screen needs `openid`/`userinfo.email`/
  `userinfo.profile` added in GCP Console] → Non-sensitive
  scopes, a maintainer click-ops step; sign-in answers 503/
  an OAuth error screen if skipped. Captured as a
  deployment task.
- [Sign-in mode drops `@login_required` from the shared
  callback] → Connect behavior is preserved by re-checking
  auth inside the connect branch; a forged callback without
  session state fails the state check before any work.

## Migration Plan

Merge → maintainer adds the three OIDC scopes to the OAuth
consent screen in GCP Console → maintainer applies the
`google_api` migration to prod manually
(`python manage.py migrate` with the prod `DATABASE_URL`,
per the migrations rule). Rollback: revert the deploy; the
migration is additive (nullable column) and harmless to an
older code version.

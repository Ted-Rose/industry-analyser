# Proposal

## Why

Public credential registration already ships — username +
optional email + password via `POST /api/accounts/register/`
and the `/accounts/register/` SPA page (archived change
`2026-10-30-add-user-registration`). What is missing is "Sign
in with Google": the existing `/google/login` flow only
attaches a Google Tasks grant to an already-authenticated
Django user — it can neither create an account nor establish
a session for an anonymous visitor. A user who wants digest
tasks must register with a password, log in, then complete a
second `/google/login` consent round-trip before subscribing.

## What Changes

- New public `GET /google/signin/` entry point in
  `google_api` — requests `openid`, `userinfo.email` and
  `userinfo.profile` (plus `auth/tasks` when `?tasks=1`),
  stashes flow mode, state, PKCE verifier, scopes and a
  sanitized `next` in the session, and redirects to Google's
  consent screen.
- `GET /google/callback` becomes the shared callback for both
  flows, branching on the session-stashed flow mode:
  `connect` keeps today's attach-grant-to-current-user
  behavior; `signin` fetches the OIDC userinfo, resolves or
  creates the Django user, establishes a session and stores
  the grant. Reusing the existing callback means no new
  redirect URI has to be registered on the OAuth client.
- `GoogleOAuthCredentials` gains a unique nullable
  `google_sub` column (one migration) so returning Google
  users resolve by stable identity, not just email.
- User resolution order: stored `google_sub` →
  Google-verified email (case-insensitive match links the
  existing account) → create a new non-staff user with a
  unique derived username and an unusable password.
- Hardening shared by both modes: the OAuth `state` param is
  verified against the session before token exchange (stashed
  today, never checked) and `next` is sanitized to a
  same-origin path (today an absolute URL would be an open
  redirect).
- Frontend: a "Sign in with Google" button plus an unchecked
  "also grant Google Tasks access" checkbox on the Login and
  Register pages — a plain link (full-page navigation), not an
  XHR. Hidden when OAuth is unconfigured, via a new
  `google_oauth_configured` key in the spa-bootstrap payload.
  `?tasks=1` with no explicit `next` defaults the post-login
  redirect to `/news/preferences/?subscribe=1` so the digest
  subscribe flow continues automatically.
- The PWA service worker adds `/google` to `BYPASS_PATHS` so
  OAuth navigations are never served from cache.

## Capabilities

### New Capabilities

(none — sign-in extends the existing auth and OAuth
capabilities)

### Modified Capabilities

- `user-auth`: Google sign-in becomes a second way to create
  and log into a non-staff account; account resolution rules
  (sub → verified email → new user) and the sign-in UI on the
  accounts SPA pages are specified.
- `google-oauth`: the web flow gains a sign-in mode sharing
  `/google/callback`, per-mode scopes, `google_sub` on the
  credentials row, and the state/next hardening above.

## Impact

- **Layers**: both — backend (`google_api/` views, urls,
  utils, models + migration, admin; `industry_analyser/
  views.py` bootstrap key; `fetcher` service worker) and
  frontend (`frontend/src/accounts/` Login/Register pages,
  shared bootstrap typing, tests, rebuilt `frontend_dist/`).
- **Data**: one `google_api` migration adding
  `google_oauth_credentials.google_sub` (unique, nullable) —
  migration file ships in the commit; the maintainer applies
  it to prod manually per the migrations rule.
- **APIs**: none — `/google/*` are plain Django views, not
  ninja ops, so `openapi.json`/`api-types.ts` are untouched.
- **Dependencies**: none new — `google-auth`,
  `google-auth-oauthlib`, `google-api-python-client` and
  `requests` are already pinned in both `requirements.txt`
  and `pyproject.toml`.
- **Config**: the OAuth client needs `openid`,
  `userinfo.email` and `userinfo.profile` added to its
  consent-screen scopes in GCP Console (non-sensitive;
  `auth/tasks` is already there). No new redirect URI, no new
  secrets — `GOOGLE_OAUTH_CLIENT_JSON` is unchanged.
- **Access tiers**: unchanged — Google-created users land in
  the existing registered-user (non-staff) tier; staff-only
  surfaces stay staff-only.

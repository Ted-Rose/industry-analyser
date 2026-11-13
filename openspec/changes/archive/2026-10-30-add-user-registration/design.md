# Design

## Context

One `NinjaAPI` at `/api/` (`industry_analyser/api.py`) with
`django_auth` as the default; public reads opt out per-op with
`auth=None`. The only login UI is `/admin/login/`
(`LOGIN_URL='/admin/login/'`), so "authenticated" today means
"the admin". Per-user FKs already exist
(`SavedVacancyFilter`, `CompanyPreference`, `ShowPreference`,
`NewsSourcePreference`) and the `accounts/` app is a stub in
`INSTALLED_APPS` whose `/accounts/` route 301s to `/`. A
parallel worktree (`industry-analyser-wt-ui-ux`) extends the
SPA bootstrap with `apps`, `is_staff` and `is_authenticated` —
key names this change matches.

## Goals / Non-Goals

**Goals:**

- Public registration + session login/logout with no new
  dependencies (ninja schemas + `django.contrib.auth`, not DRF).
- A public login/register SPA that every login bounce lands on.
- Split "authenticated" into staff vs registered users without
  touching per-user feature semantics.
- Mirror the Bible Research credential rules (iexact usernames,
  password validators, uniform login failure).

**Non-Goals:**

- Email verification, password reset, social login, profile
  editing, admin user management.
- Changing receipts' hard-coded `ADMIN_USERNAME` dataset — it
  stays a single-admin feature by design.
- Rate limiting / throttling — the repo has no mechanism (no
  DRF, no ratelimit dep); see Open Questions.
- A shared TopNav/user menu — the ui-ux worktree owns nav; this
  change only ships the bootstrap keys it reads.

## Decisions

### URL surface: `/accounts/` for the SPA, `/api/accounts/` for ops

The mount keeps the plural Django convention and the existing
`accounts` URL name (test-pinned `reverse('accounts')` still
resolves to `/accounts/`). The 301 stub is deleted — the stub
page is replaced by the thing it was a placeholder for.
`spa_url_for`'s mechanical `/api/accounts/x` → `/accounts/x`
rewrite lands on real client routes. Router lives in
`accounts/api.py`, registered in `industry_analyser/urls.py`
with the other `add_router` calls. Alternative considered —
`/api/auth/` + `/account/` — rejected: invents a second name
for the `accounts` app and orphans the existing URL name.

### Staff enforcement: `staff_auth` per-op + `staff_member_required` shell

New `staff_auth` callable in `industry_analyser/api.py` next to
the error handlers:

- anonymous → return `None` → ninja raises `AuthenticationError`
  → the existing 401 `login_url` handshake (unchanged shape).
- authenticated non-staff → raise `HttpError(403, ...)` → the
  uniform `{error: 'forbidden', detail, code}` body. No
  `login_url`: re-authenticating cannot help.

Applied per-op (`auth=staff_auth`) so the access tier is
declarative at the router. For SPA pages, `spa_shell` (the
`react_app` inner view) swaps `@login_required` for
`@staff_member_required`, which 302s both anonymous and
non-staff visitors to `admin:login` — staff-only pages bounce
to the staff login, keeping the status-quo UX and the
"admin login still reachable" requirement for free.
Alternative considered — a custom decorator sending anonymous
visitors to `/accounts/login/` and non-staff to a 403 page:
rejected as more code for a page tier anonymous users cannot
usefully log into anyway.

### `LOGIN_URL` and the 401 handshake

`LOGIN_URL` becomes `'/accounts/login/'`. Per-user
`login_required` surfaces (`news:preferences`) then bounce to
the public login page; staff pages never reach `LOGIN_URL`
because `staff_member_required` short-circuits to
`admin:login`. The API 401 handler builds
`login_url='/accounts/login/?next=<spa_url>'` uniformly —
including for staff-only endpoints: an anonymous caller is sent
to the one public login page, and a non-staff login simply
earns a 403 there. Alternative — emitting `/admin/login/` for
staff endpoints — rejected: it leaks the staff/registered
split into a heuristic (the handler cannot know whether the
session that failed was anonymous or non-staff) and splits the
client's redirect target.

### `me` is public and never 401s

`GET /api/accounts/me/` returns 200 `{user, is_authenticated}`
for both cases. A 401 would trigger `apiFetch`'s
navigate-to-`login_url` path — a state-check endpoint must not
redirect the page that calls it. `register`/`login` are
`auth=None` by necessity (anonymous must reach them); `logout`
keeps default `django_auth` — CSRF comes free and anonymous
logout getting a 401 is correct.

### CSRF on the auth=None POSTs

ninja wraps every operation in a `csrf_exempt` view; CSRF for
session-auth ops is enforced inside `django_auth`, which
`auth=None` ops skip. The register/login ops therefore get an
explicit `@csrf_protect` on the endpoint function — the
`/accounts/` shell already carries `ensure_csrf_cookie` via
`react_app_public` and `client.ts` already sends
`X-CSRFToken`. This is cheap protection against login-CSRF
(planting an attacker's session on a victim). Alternative —
`NinjaAPI(csrf=True)` globally — rejected for blast radius:
it changes every op, including future public mutations.

### Credential rules (mirroring Bible Research)

- username `^\S+$`, iexact uniqueness — required for the
  iexact login lookup to stay deterministic.
- email optional, iexact-unique when non-empty (blank → `''`).
- `validate_password(password, user=User(username, email))`
  runs all four configured validators, including
  similarity against the unsaved user's username/email.
- `password == password_confirm` checked explicitly.
- `User.objects.create_user(...)` wrapped so a lost
  uniqueness race surfaces `IntegrityError` → 400, not 500.
- New `accounts/backends.py` `CaseInsensitiveAuthBackend`
  (`username__iexact`, prefers the exact-case match, runs the
  hasher once on a missing user, `user_can_authenticate` for
  `is_active`); `AUTHENTICATION_BACKENDS` is set to it. Login
  failures are one uniform 401 `invalid_credentials` — no
  user enumeration.

Register/login auto-login via `django.contrib.auth.login` —
with a single configured backend, `authenticate()`/`create_user`
paths supply `user.backend` so the call needs no extra wiring.

### Validation plumbing

The repo has no serializer layer; per-endpoint checks raise
`ApiHttpError(400, detail, code=<slug>)`, which the existing
`_on_http_error` handler already shapes into `{error:
'bad_request', detail, code}`. Missing/mistyped fields still
get ninja's 422 `validation_error`. Error codes:
`invalid_username`, `username_taken`, `email_taken`,
`weak_password`, `password_mismatch`, `invalid_credentials`.

### Bootstrap keys

`_spa_shell`'s bootstrap gains `is_authenticated` and
`is_staff` — the exact names the ui-ux worktree uses, so the
branches merge semantically (this change deliberately does NOT
add `apps`, which is that branch's feature). `useBootstrap`'s
interface gains the two optional booleans.

### Landing page and utility mounts

`'accounts/'` joins `_LANDING_SKIP_ROUTES` — the auth SPA is a
utility page, not a mini-app, and keeping it excluded preserves
the existing landing-discovery test
(`test_infra_mounts_and_self_are_excluded` already asserts
`/accounts/` is absent).

### Secrets and caching landmines

- `sentry.py` `_SENSITIVE_PATH_PREFIXES` gains
  `/api/accounts/` — register/login bodies carry passwords.
- `fetcher/templates/fetcher/sw.js` `BYPASS_PATHS` gains
  `/accounts` (the fetch handler must never serve a cached auth
  page) and `PWA_CACHE_VERSION` bumps `v9` → `v10`.

### Frontend

New `frontend/src/accounts/` entry mounted with
`<BrowserRouter basename="/accounts">` (the per-SPA
convention): routes `/` (account page — shows the `me`
payload and logout, or login/register links for anonymous),
`/login`, `/register`. On success the pages navigate via
`window.location.assign(target)` — a full reload so the next
page's bootstrap reflects the new session. `?next=` is
sanitized to a same-origin pathname (`^/(?!/)`, else fall back
to `/`) — the open-redirect guard. `vite.config.ts` gains the
`accounts` input and the `gen:types` loop gains the entry.
`client.ts`'s opaque-redirect fallback moves to
`/accounts/login/?next=...`. Cross-app affordance gating
(hide "add keyword" for non-staff etc.) rides on
`bootstrap.is_staff` and is follow-up polish, not part of this
change's contract.

### Access matrix

| Surface | Before | After |
|---|---|---|
| Public GETs, landing, public SPAs | public | public |
| `register/`, `login/`, `me/` | — | `auth=None` |
| `logout/` | — | authenticated |
| Company preference PUT | authed | authed (any user) |
| Saved-filters CRUD | authed | authed (any user) |
| TV reaction POSTs | authed | authed (any user) |
| `news:preferences` | authed | authed (any user) |
| `POST /api/vacancies/keywords/` | authed | **staff** |
| `POST /api/classified-ads/regions/config/` | authed | **staff** |
| `/dashboard/` + `GET /api/dashboard/` | authed | **staff** |
| `/receipts/` + `GET /api/receipts/` | authed | **staff** |

## Risks / Trade-offs

- [Registered user who bookmarked a staff page keeps getting
  bounced to admin login] → acceptable; admin login's error
  state explains missing staff rights.
- [Login CSRF left unenforced would allow session planting] →
  `csrf_protect` on both ops; the cookie is guaranteed by
  `ensure_csrf_cookie` on the public shell.
- [`me` as `auth=None` slightly widens the schema's public
  surface] → returns only the caller's own row; user-id
  enumeration is not possible.
- [Case-insensitive uniqueness relies on app-level checks —
  Postgres collation keeps `Alice`/`alice` insertable by a
  raced second request] → `IntegrityError` → 400 covers the
  race; no DB constraint added (would need a functional index —
  acceptable residual risk, same as Bible Research).
- [Branch overlap with `industry-analyser-wt-ui-ux`] → key
  names matched deliberately (`is_staff`, `is_authenticated`);
  whichever lands second rebases a small bootstrap dict edit.
- [Unthrottled register/login enables credential stuffing] →
  bounded by uniform errors + password hashing cost; flagged
  as optional hardening below rather than a new dependency.

## Migration Plan

No migrations (default `User`, no schema change). Deploy order
is a single merge: backend, SPA, and `login_url` contract
change atomically — a half-deploy would only mix which login
page bounces render, all of which still work. Prod DB untouched.
Rollback: revert the merge; sessions are plain Django sessions,
nothing to unwind.

## Open Questions

- Rate limiting on `register/`/`login/`: no throttle mechanism
  exists in the repo (DRF throttles don't apply). If wanted,
  a tiny `django.core.cache`-based attempt counter (5/min per
  IP) can be added inside the two endpoints later without a
  dependency — deferring unless asked.

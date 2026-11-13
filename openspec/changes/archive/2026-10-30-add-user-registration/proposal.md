# Proposal

## Why

Today the only login UI is `/admin/login/` and "logged in" means
"is the admin". Per-user data models already exist
(`SavedVacancyFilter`, `CompanyPreference`, `ShowPreference`,
`NewsSourcePreference`) and every mutating endpoint accepts any
authenticated user — but there is no way for a non-admin person
to get an account. This change adds public registration plus a
session-auth login/logout surface, and splits "authenticated"
into two tiers: staff (everything that is login-required today)
and registered users (genuinely per-user features).

## What Changes

- New `accounts` API router at `/api/accounts/`: `register/`,
  `login/`, `logout/` (POST) and `me/` (GET). Session auth only —
  register and login create a real Django session; no DRF, no
  tokens, no new dependencies.
- Registration: nickname (username) + optional email + password
  + confirmation. Username must match `^\S+$` and be unique
  case-insensitively; email is unique when provided; password
  runs the configured `AUTH_PASSWORD_VALIDATORS`; success
  auto-logs-in and returns the user payload.
- Case-insensitive auth backend (`username__iexact`, prefers an
  exact-case match, runs the password hasher once on a missing
  user) wired via `AUTHENTICATION_BACKENDS`.
- **BREAKING** `LOGIN_URL` moves from `/admin/login/` to
  `/accounts/login/`; the JSON 401 handshake's `login_url` and
  the SPA client's opaque-redirect fallback follow. The Django
  admin login stays reachable at `/admin/login/` for staff.
- **BREAKING** access split (previously: everything behind
  `django_auth`/`login_required` accepted any authenticated
  user):
  - Staff-only: `/dashboard/` + `GET /api/dashboard/`,
    `/receipts/` + `GET /api/receipts/` (a single admin user's
    private data — stays hard-coded to `ADMIN_USERNAME`),
    `POST /api/vacancies/keywords/` and
    `POST /api/classified-ads/regions/config/` (global scrape
    configuration, not per-user data). Authenticated non-staff
    callers get 403 `{error: 'forbidden'}`; anonymous callers
    keep the 401 `login_url` handshake.
  - Registered users (unchanged tier — any authenticated user):
    `PUT /api/vacancies/companies/<pk>/preference/`, the
    saved-filters CRUD under `/api/vacancies/filters/`, the TV
    reaction POSTs, and the `news:preferences` page.
  - Public (unchanged): every `auth=None` GET, the landing page,
    and the public SPA mounts.
- New public SPA entry `accounts` (`frontend/src/accounts/`)
  mounted at `/accounts/` via `react_app_public` — replaces the
  retired 301 stub; routes for login, register, and a minimal
  account page. The mount is excluded from the landing page's
  mount discovery (`_LANDING_SKIP_ROUTES`).
- The SPA bootstrap payload gains `is_authenticated` and
  `is_staff` (key names chosen to match the in-flight ui-ux
  worktree, which adds `apps` itself).
- Auth hardening: `sentry_before_send` scrubs request bodies
  under `/api/accounts/`; `sw.js` adds `/accounts` to
  `BYPASS_PATHS` (cache version bump); `csrf_protect` on the
  `auth=None` register/login ops.

## Capabilities

### New Capabilities

- `user-auth`: public registration, session login/logout, the
  current-user endpoint, case-insensitive credential handling,
  and the staff-vs-registered-vs-anonymous access tiers.

### Modified Capabilities

- `spa-api-contract`: the 401 `login_url` target moves to
  `/accounts/login/`, the shared client fallback follows, the
  login-required shell becomes staff-required, and the bootstrap
  payload gains `is_authenticated`/`is_staff`.

## Impact

- **Backend:** `accounts/` (new `api.py`, `backends.py`,
  rewritten `tests.py`), `industry_analyser/api.py`
  (`staff_auth`, login_url target), `industry_analyser/views.py`
  (staff shell, bootstrap keys, landing skip), `urls.py`
  (accounts mount, router registration), `settings.py`
  (`LOGIN_URL`, `AUTHENTICATION_BACKENDS`), `sentry.py`,
  `fetcher/templates/fetcher/sw.js`, `fetcher/views.py`
  (cache bump), plus `auth=staff_auth` on the keywords,
  region-config, dashboard and receipts ops.
- **Frontend:** new `frontend/src/accounts/` entry,
  `shared/api/client.ts` fallback URL, `useBootstrap` typing,
  `vite.config.ts` input, the `gen:types` entry list,
  `frontend/openapi.json`, generated `api-types.ts` files and a
  recommitted `frontend_dist/` build.
- **Tests:** updated `login_url` assertions in fetcher /
  tv_programs / classified_ads / receipts / scrape_jobs test
  files; new auth + access-matrix tests in `accounts/tests.py`.
- **Layers impacted:** both.
- **Migrations:** none — default `django.contrib.auth` User,
  no schema changes.

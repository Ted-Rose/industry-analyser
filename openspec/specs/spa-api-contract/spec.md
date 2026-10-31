# SPA ↔ API Contract Specification

## Purpose

Defines the contract spanning the Django backend and the
React/Vite SPA: the single django-ninja API at `/api/`, the
uniform error body, session-auth + CSRF behavior, the 401
login-redirect handshake, the shared SPA shell view, the
frontend `apiFetch` client, and the committed OpenAPI
schema/type-generation drift check.

## Requirements

### Requirement: One ninja API under /api/

All JSON endpoints SHALL live on the single `NinjaAPI` in
`industry_analyser/api.py`, mounted at `/api/` before the SPA
catch-alls, with per-app routers added via `api.add_router()`.
Default auth is ninja `django_auth` (session cookie, CSRF
enforced on unsafe methods); public reads opt out per-op with
`auth=None`. `/api/docs` and the served schema are
staff-only — the schema ships via committed
`frontend/openapi.json` instead.

#### Scenario: Anonymous session hits an authed endpoint

- **WHEN** an unauthenticated request reaches an endpoint that
  did not opt out with `auth=None`
- **THEN** the response is a JSON 401, never an HTML login
  redirect

#### Scenario: Unsafe method without CSRF

- **WHEN** a POST/PUT/PATCH/DELETE lacks a valid CSRF token
- **THEN** Django session auth rejects it before the endpoint
  runs

### Requirement: Uniform error body

Non-2xx API responses SHALL use the shape `{error: <slug>,
detail: <detail>}` — except the 401 handshake body, which
carries `login_url` instead of `detail` — with optional
`code` (endpoint-set catalog key via `ApiHttpError`,
defaulting to the status slug) and optional `params`. The
status→slug map is fixed in `_ERROR_SLUGS` (e.g. 401
`unauthenticated`, 404 `not_found`, 422 `validation_error`,
429 `throttled`, 500 `server_error`).

#### Scenario: Endpoint raises ApiHttpError with a code

- **WHEN** an endpoint raises
  `ApiHttpError(409, 'msg', code='already_exists')`
- **THEN** the body is `{error: 'conflict', detail: 'msg',
  code: 'already_exists'}` with status 409

#### Scenario: Schema validation fails

- **WHEN** request data fails ninja schema validation
- **THEN** the response is 422 with `{error:
  'validation_error', detail: <error list>}`, not ninja's bare
  `{detail: [...]}`

#### Scenario: Unhandled exception

- **WHEN** an endpoint raises an unhandled exception
- **THEN** the response is 500 `{error: 'server_error',
  detail: 'Internal Server Error'}`, the traceback is logged,
  and a Sentry event tagged `error_code:internal_error` is
  captured

### Requirement: 401 login-redirect handshake

Authentication failures SHALL return 401 `{error:
'unauthenticated', login_url:
'/accounts/login/?next=<spa_url>'}` where `spa_url_for()`
rewrites the `/api/<app>/<sub>` request path to the SPA page
that issued it — `login_url`/`next` MUST never point back at
an `/api/` path.

#### Scenario: Dashboard API 401 maps to the SPA mount

- **WHEN** `GET /api/dashboard/` returns 401
- **THEN** `login_url` is `/accounts/login/?next=/dashboard/`
  (`SPA_BASES` pins `dashboard` → `/dashboard/`; `/` itself is
  the public landing page)

#### Scenario: Query string is preserved

- **WHEN** `POST /api/vacancies/filters/` returns 401
- **THEN** the `next` parameter carries `/vacancies/`
  (`filters` remaps to the vacancy list page via `SPA_SUBPATHS`;
  GET /filters/ itself is public — `auth=None`)

#### Scenario: Authenticated non-staff gets 403, not a bounce

- **WHEN** an authenticated non-staff request reaches a
  staff-only endpoint (e.g. `GET /api/receipts/`)
- **THEN** the response is 403 `{error: 'forbidden'}` — no
  `login_url`, since logging in again cannot help

#### Scenario: Sub-path remap lands on the owning SPA page

- **WHEN** an authed op under a remapped sub-path 401s — e.g.
  `PUT /api/vacancies/companies/{pk}/preference/`
- **THEN** `next` is `/companies/` via `SPA_SUBPATHS`, not the
  nonexistent `/vacancies/companies/`

#### Scenario: Login surface is the single login_url target

- **WHEN** any API 401 emits a `login_url`
- **THEN** it targets the public `/accounts/login/` SPA route;
  the `/admin/login/` page stays reachable for staff but is
  never emitted by the API

#### Scenario: Credential failure on the login endpoint

- **WHEN** the login endpoint itself rejects credentials
- **THEN** the response is a 401 WITHOUT `login_url` (see the
  user-auth spec)

### Requirement: Shared SPA shell

Every SPA mount SHALL serve `react_app` (staff-required) or
`react_app_public`: GET/HEAD renders `spa_shell.html` with
`vite_entry = src/<entry>/main.tsx`; any other method 404s.
`entry` must match `[a-z0-9_]+` and maps to a
`frontend/src/<entry>/` folder and manifest key. The shell
injects a `bootstrap` JSON — no VITE_* build vars reach the
page.

#### Scenario: Client-side route loads the shell

- **WHEN** a GET hits a `<path:subpath>` route under an SPA
  mount (e.g. `/vacancies/123/`)
- **THEN** the shell renders and React Router resolves the
  page client-side

#### Scenario: Non-GET request on an SPA path

- **WHEN** a POST targets an SPA-owned URL
- **THEN** the view raises Http404 — mutations live under
  `/api/`

#### Scenario: Missing or stale manifest

- **WHEN** prod mode and `manifest.json` lacks the entry
- **THEN** `manifest_ready` is false and the template shows a
  diagnostic instead of crashing on `{% vite_asset %}`

#### Scenario: API misses never serve the shell

- **WHEN** a request misses under `/api/`, `/admin/`, or
  `/static/` after the real mounts
- **THEN** a `terminal_404` drain answers 404 (replicating
  APPEND_SLASH when the slashed variant resolves) — the
  terminal catch-all (which renders the public landing page)
  is always the last url pattern

#### Scenario: Non-staff visitor hits a staff SPA mount

- **WHEN** an anonymous OR authenticated non-staff GET hits a
  `react_app` mount (`/dashboard/`, `/receipts/` — staff-only
  pages)
- **THEN** `staff_member_required` redirects to the admin
  login instead of serving a bundle whose API calls would all
  403

#### Scenario: Plain login_required surfaces use LOGIN_URL

- **WHEN** an anonymous user hits a per-user login-required
  page outside the SPA shell (e.g. news preferences)
- **THEN** ordinary `login_required` redirects to `LOGIN_URL`
  (`/accounts/login/`), not the admin login

#### Scenario: Auth flags ride the bootstrap payload

- **WHEN** any SPA shell renders for an authenticated staff
  user
- **THEN** `bootstrap` carries `user`, `is_authenticated`
  (true), `is_staff` (true) and
  `sentry.{dsn,environment,release}`; anonymous renders carry
  false for both flags

### Requirement: Frontend client honors the contract

`shared/api/client.ts` `apiFetch()` SHALL send cookies
same-origin with `redirect: 'manual'`, attach `X-CSRFToken`
from the `csrftoken` cookie on unsafe methods, and throw
`ApiError` (status + parsed body) for other non-2xx. On 401
with `login_url`/`authorization_url` it navigates there and
returns a never-resolving promise; opaque redirects/status 0
navigate to `/accounts/login/?next=<current path>`.

#### Scenario: 401 with login_url

- **WHEN** a response is 401 with `login_url` in the JSON body
- **THEN** the browser navigates to it and the caller's
  promise never resolves — the page is leaving

#### Scenario: Plain error surfaces detail

- **WHEN** a response is non-2xx without auth fields
- **THEN** `errorDetail()` returns the body's `detail` string
  for user-facing messages

### Requirement: Committed schema with drift check

`frontend/openapi.json` SHALL be committed and regenerated by
`manage.py export_openapi_schema --output
frontend/openapi.json` (django-ninja's command); `npm run
gen:types` regenerates `src/<entry>/api-types.ts` for every
SPA entry. CI runs both and `git diff --exit-code` fails the
PR on drift.

#### Scenario: Endpoint schema changes without regeneration

- **WHEN** an API change alters the schema but
  `openapi.json`/`api-types.ts` are not regenerated
- **THEN** the frontend-checks workflow fails with a non-empty
  diff

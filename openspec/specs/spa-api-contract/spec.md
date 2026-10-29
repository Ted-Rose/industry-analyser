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

Authentication failures SHALL return `{error:
'unauthenticated', login_url: '/admin/login/?next=<spa_url>'}`
where `spa_url_for()` rewrites the `/api/<app>/<sub>` request
path to the SPA page that issued it — `login_url`/`next` MUST
never point back at an `/api/` path. `SPA_BASES` and
`SPA_SUBPATHS` map APIs whose owning page lives elsewhere
(e.g. `dashboard` → `/`, `vacancies/companies` → `/companies/`).

#### Scenario: Dashboard API 401 maps to site root

- **WHEN** `GET /api/dashboard/` returns 401
- **THEN** `login_url` is `/admin/login/?next=/` (the
  dashboard SPA mounts at the root)

#### Scenario: Query string is preserved

- **WHEN** `GET /api/vacancies/filters/?page=2` returns 401
- **THEN** the `next` parameter carries
  `/vacancies/?page=2` (`filters` remaps to the vacancy list
  page via `SPA_SUBPATHS` and the query survives)

### Requirement: Shared SPA shell

Every SPA mount SHALL serve `react_app` (login-required) or
`react_app_public`: GET/HEAD renders `spa_shell.html` with
`vite_entry = src/<entry>/main.tsx`; any other method 404s.
`entry` must match `[a-z0-9_]+` and maps to a
`frontend/src/<entry>/` folder and manifest key. The shell
injects a `bootstrap` JSON carrying `user` and
`sentry.{dsn,environment,release}` — no VITE_* build vars.

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
  APPEND_SLASH when the slashed variant resolves) — the root
  catch-all SPA is always the last url pattern

### Requirement: Frontend client honors the contract

`shared/api/client.ts` `apiFetch()` SHALL send cookies
same-origin with `redirect: 'manual'`, attach `X-CSRFToken`
from the `csrftoken` cookie on unsafe methods, and throw
`ApiError` (status + parsed body) for other non-2xx. On 401
with `login_url`/`authorization_url` it navigates there and
returns a never-resolving promise; opaque redirects/status 0
navigate to `/admin/login/?next=<current path>`.

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

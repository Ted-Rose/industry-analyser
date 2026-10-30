# Tasks

Worktree note: this repo has no `venv` in worktrees — run
`manage.py` via `../industry-analyser/venv/bin/python` and tests
with `DATABASE_URL=sqlite:///db.sqlite3` as in the commands
below.

## 1. Backend — auth plumbing

- [x] 1.1 backend: create `accounts/backends.py` with
  `CaseInsensitiveAuthBackend` (`username__iexact`, prefers the
  exact-case match, runs the hasher once on a missing user,
  `user_can_authenticate` for `is_active`) and set
  `AUTHENTICATION_BACKENDS` in `industry_analyser/settings.py`
  to it; verify a test user created as `Alice` authenticates as
  `alice`.
- [x] 1.2 backend: create `accounts/api.py` — a ninja `Router`
  with `register/`, `login/`, `logout/` (POST) and `me/` (GET),
  input/output `Schema`s, the validation rules from the
  user-auth spec (`ApiHttpError` codes `invalid_username`,
  `username_taken`, `email_taken`, `weak_password`,
  `password_mismatch`, `invalid_credentials`), `csrf_protect`
  on the two `auth=None` POSTs, `IntegrityError` → 400 on
  `create_user`, and auto-login on register/login; `me`
  returns `{user, is_authenticated}` for both cases.
- [x] 1.3 backend: register the router in
  `industry_analyser/urls.py` via
  `api.add_router('/accounts/', accounts_router)`; verify
  `GET /api/accounts/me/` answers 200 anonymously after
  `python manage.py check` + a shell probe.
- [x] 1.4 backend: add `staff_auth` to `industry_analyser/api.py`
  (anonymous → `None`/401 handshake; authenticated non-staff →
  `HttpError` 403 `{error: 'forbidden'}`) and apply it to
  `GET /api/dashboard/` (`scrape_jobs/api.py`),
  `GET /api/receipts/` (`receipts/api.py`),
  `POST /api/vacancies/keywords/` (`fetcher/api.py`) and
  `POST /api/classified-ads/regions/config/`
  (`classified_ads/api.py`); leave the per-user ops on the
  default `django_auth`; verify with the access-matrix tests
  in 1.8.
- [x] 1.5 backend: change `LOGIN_URL` to `'/accounts/login/'`
  in `settings.py` and the `_on_unauthenticated` handler in
  `industry_analyser/api.py` to emit
  `/accounts/login/?next=<spa_url>`; verify an anonymous
  `POST /api/vacancies/filters/` 401s with
  `login_url` starting `/accounts/login/`.
- [x] 1.6 backend: in `industry_analyser/views.py` swap
  `@login_required` for `@staff_member_required` on
  `spa_shell`, add `is_authenticated`/`is_staff` to the
  `_spa_shell` bootstrap payload, and add `'accounts/'` to
  `_LANDING_SKIP_ROUTES`; verify `/dashboard/` 302s to the
  admin login for anonymous AND non-staff users and the
  bootstrap JSON carries the new keys.
- [x] 1.7 backend: add `'/api/accounts/'` to
  `_SENSITIVE_PATH_PREFIXES` in `industry_analyser/sentry.py`,
  add `'/accounts'` to `BYPASS_PATHS` in
  `fetcher/templates/fetcher/sw.js`, and bump
  `PWA_CACHE_VERSION` `v9` → `v10` in `fetcher/views.py`;
  verify the sentry scrub test extension passes.
- [x] 1.8 backend: rewrite `accounts/tests.py` — drop the 301
  tests, keep the `reverse('accounts')` name check against the
  new SPA mount, add register validation matrix (whitespace
  username, iexact username/email duplicates, weak/similar/
  mismatched passwords), iexact login + inactive/wrong-password
  uniformity, me/logout behavior, and the staff-vs-registered
  access matrix (403 non-staff on the four staff ops, 200s on
  the per-user ops); update the pinned `login_url` assertions
  in `fetcher/tests.py`, `tv_programs/tests.py`,
  `classified_ads/tests.py`, `receipts/tests.py` (and
  `scrape_jobs` if asserted) plus the sentry-prefix test in
  `industry_analyser/tests.py`; verify with
  `DATABASE_URL=sqlite:///db.sqlite3 ../industry-analyser/venv/
  bin/python manage.py test accounts fetcher tv_programs
  classified_ads receipts scrape_jobs industry_analyser news`.

## 2. Backend — accounts SPA mount

- [x] 2.1 backend: replace the `/accounts/` 301 in
  `industry_analyser/urls.py` with `react_app_public` partials
  (`entry='accounts'`, `title='Sign in'`, `name='accounts'`
  index + `<path:subpath>` catch-all); verify
  `GET /accounts/login/` renders `spa_shell.html` (200,
  `id="root"`, csrftoken cookie set) for an anonymous user.
- [x] 2.2 backend: run `python manage.py check` and confirm no
  warnings beyond the known set.

## 3. Frontend — accounts SPA

- [x] 3.1 frontend: add the `accounts` input to
  `frontend/vite.config.ts` and the entry to the `gen:types`
  loop in `frontend/package.json`; verify `npm run gen:types`
  writes `src/accounts/api-types.ts` once 4.1 lands (until
  then generate it from the schema artifact).
- [x] 3.2 frontend: create `frontend/src/accounts/` —
  `main.tsx` (mirrors the per-SPA boilerplate,
  `basename="/accounts"`), `App.tsx` with routes `/`,
  `/login`, `/register`, `api.ts` typed off `api-types.ts`,
  and `routes/` pages: Login + Register forms posting to
  `/api/accounts/login|register/` and an Account index page
  showing `me` plus logout; sanitize `?next=` to a
  same-origin pathname (`^/(?!/)`, default `/`) and finish
  auth flows with `window.location.assign(next)`; verify via
  `npm run typecheck` and a vitest smoke test for the next
  sanitization.
- [x] 3.3 frontend: update `shared/api/client.ts`'s
  opaque-redirect/status-0 fallback to navigate to
  `/accounts/login/?next=<current path>` and extend
  `useBootstrap`'s `BootstrapPayload` with
  `is_authenticated?: boolean` and `is_staff?: boolean`;
  verify existing client tests still pass (`npm test`).
- [x] 3.4 frontend: add vitest coverage for the accounts pages
  (login submit → `window.location.assign` with a sanitized
  `next`; error detail surfaced from `{error, detail}`) in
  `frontend/src/accounts/`; verify `npm test` is green.

## 4. Schema, build, and integration

- [x] 4.1 both: regenerate `frontend/openapi.json`
  (`python manage.py export_openapi_schema --output
  frontend/openapi.json`) and run `npm run gen:types`; verify
  the accounts ops appear in the schema and a fresh
  `api-types.ts` lands in `src/accounts/`.
- [x] 4.2 frontend: `cd frontend && npm run build` and recommit
  `frontend_dist/`; verify `manifest.json` contains an
  `src/accounts/main.tsx` entry.
- [x] 4.3 backend: re-run the scoped test suite from 1.8 plus
  `news` and confirm green; run `npm run typecheck` and
  `npm test` in `frontend/`.
- [x] 4.4 both: manual smoke via `./dev.sh` — register a user
  on `/accounts/register/`, land back on `?next=` page, log
  out on `/accounts/`, log in case-insensitively, and confirm
  a non-staff session 403s on `GET /api/dashboard/` while the
  admin account still reaches `/admin/`.

## Workflow follow-up

- Archive this change after the PR merges:
  `openspec archive-change add-user-registration` on master —
  the `user-auth` spec becomes a new capability and the
  `spa-api-contract` delta folds into the base spec.

# Tasks

## 1. Model + migration

- [x] 1.1 backend: Add `google_sub =
  models.CharField(max_length=255, unique=True, null=True,
  blank=True)` to `GoogleOAuthCredentials` in
  `google_api/models.py`, and add `'google_sub'` to
  `_SAFE_FIELDS` in `google_api/admin.py`. Verify:
  `python manage.py check` passes.
- [x] 1.2 backend: Generate the migration file only —
  `python manage.py makemigrations google_api` (touches no
  DB; do NOT run `migrate`). Verify: a
  `google_api/migrations/0002_*.py` exists and
  `awk 'length > 79 {print FILENAME":"NR}'` reports no long
  lines in the edited files.

## 2. Sign-in flow backend

- [x] 2.1 backend: In `google_api/utils.py` add
  `GOOGLE_SIGNIN_SCOPES = ['openid',
  'https://www.googleapis.com/auth/userinfo.email',
  'https://www.googleapis.com/auth/userinfo.profile']` and a
  `USERINFO_ENDPOINT =
  'https://openidconnect.googleapis.com/v1/userinfo'`
  constant. No new dependencies — reuse
  `google_auth()`/`InstalledAppFlow`.
- [x] 2.2 backend: In `google_api/views.py` add a
  `_sanitize_next(value)` helper (same-origin relative path
  only — `/` prefix, not `//`; else `/`) and use it in both
  `login_view` and the new `signin_view`.
- [x] 2.3 backend: Add `signin_view(request)` (public):
  503 when `GOOGLE_APP_SECRETS_PATH` is empty; scopes =
  `GOOGLE_SIGNIN_SCOPES` (+ `GOOGLE_TASKS_SCOPES` when
  `?tasks=1`); stash `state`, `oauth_scopes`,
  `oauth_code_verifier`, `oauth_flow='signin'` and
  `oauth_redirect_url` (sanitized `next`; default
  `/news/preferences/?subscribe=1` when `tasks=1` and no
  `next`, else `/`) in the session; stash the same keys with
  `oauth_flow='connect'` in `login_view`; redirect to the
  authorization URL.
- [x] 2.4 backend: In `google_api/urls.py` add
  `path('signin/', views.signin_view, name='signin')` plus a
  `path('signin', RedirectView.as_view(url=
  '/google/signin/'), name='signin_noslash')` mirroring the
  existing `login` slashless drain (the landing catch-all
  swallows it before APPEND_SLASH).
- [x] 2.5 backend: Rewrite `callback` — drop
  `@login_required`; pop `oauth_flow` (default `connect`);
  verify `request.GET['state']` equals the session-stashed
  `state` BEFORE `fetch_token` (mismatch → discard OAuth
  session keys + redirect to the mode's start); then branch:
  `connect` requires `request.user.is_authenticated` (else
  the `login_required`-style redirect to `LOGIN_URL`) and
  keeps today's `update_or_create` + `google_sub` write;
  `signin` calls the resolver in 2.6, `auth_login(request,
  user, backend='accounts.backends.
  CaseInsensitiveAuthBackend')`, `update_or_create`s the
  credentials row (tokens, scopes, `google_sub`), redirects
  to `next`. Userinfo fetch via
  `flow.authorized_session().get(USERINFO_ENDPOINT)`;
  non-200/missing `sub` → redirect to `/accounts/login/`
  with `next` preserved. Denied/failed exchange → connect →
  `/google/login`, signin → `/accounts/login/` (existing
  exception set).
- [x] 2.6 backend: Add the user resolver (suggest
  `google_api/signin.py`): input userinfo dict; order —
  credentials row with `google_sub == sub` →
  `User.objects.filter(email__iexact=email).order_by('id').
  first()` when `email_verified` → else create (unusable
  password, unique `^\S+$` username derived from the email
  local-part with `-N` suffix loop, fallback
  `google-<sub[:16]>`, email written only when verified).
  Log a warning when overwriting a different `google_sub`.
  `logging.getLogger('google_api')`, max 79-char lines.

## 3. Bootstrap + service worker

- [x] 3.1 backend: Add `'google_oauth_configured':
  bool(settings.GOOGLE_APP_SECRETS_PATH)` to the `bootstrap`
  dict in `industry_analyser/views.py::_spa_shell_context`.
- [x] 3.2 frontend: Add `'/google'` to `BYPASS_PATHS` in
  `fetcher/templates/fetcher/sw.js` and bump
  `PWA_CACHE_VERSION` in `fetcher/views.py`.

## 4. Frontend

- [x] 4.1 frontend: New `frontend/src/accounts/GoogleSignIn.
  tsx` — reads `useBootstrap`, renders nothing when
  `google_oauth_configured` is falsy; otherwise a secondary
  `Button as="a"` linking `/google/signin/?next=<safeNext(
  search)>` plus an unchecked checkbox "Also allow Google
  Tasks access (news digest)" that appends `tasks=1`; takes
  `search` (or reads `useLocation`) so `next` round-trips.
- [x] 4.2 frontend: Mount `<GoogleSignIn>` on
  `routes/Login.tsx` and `routes/Register.tsx` below the
  credential form (e.g. an "or" divider). Keep all existing
  form behavior.
- [x] 4.3 frontend: Add `google_oauth_configured?: boolean`
  to `BootstrapPayload` in
  `frontend/src/shared/hooks/useBootstrap.ts` (explicit field
  over the index signature).
- [x] 4.4 frontend: Extend `routes/Login.test.tsx` /
  `routes/Register.test.tsx`: button links to
  `/google/signin/` with sanitized `next`; ticking the
  checkbox adds `tasks=1`; section absent when the bootstrap
  payload lacks the flag (stub `#spa-bootstrap` per existing
  test patterns).
- [x] 4.5 frontend: `cd frontend && npm run typecheck &&
  npm test`, then `npm run build` and recommit the tracked
  `frontend_dist/` output.

## 5. Backend tests

- [x] 5.1 backend: Extend `google_api/tests.py` (reuse
  `CredentialsTestCase` + `patch(
  'google_api.views.InstalledAppFlow.
  from_client_secrets_file')`): `signin/` stashes
  `oauth_flow='signin'` + scopes and redirects to the consent
  URL; `tasks=1` adds `auth/tasks` to `oauth_scopes`;
  `next=https://evil/` stashes `/`; unconfigured → 503;
  slashless `/google/signin` → `/google/signin/`.
- [x] 5.2 backend: Callback sign-in tests with a mocked Flow
  (`flow.fetch_token`, `flow.credentials`,
  `flow.authorized_session().get` returning userinfo JSON):
  new user created + logged in + credentials row with
  `google_sub`; `sub` match resolves the stored user; verified
  email links an existing password user; `email_verified:
  False` never links (new user, empty email); denied /
  InvalidGrant → `/accounts/login/`; state mismatch → no
  `fetch_token` call; `tasks=1` with no `next` defaults to
  `/news/preferences/?subscribe=1`.
- [x] 5.3 backend: Regression — anonymous `/google/callback`
  without stashed mode still redirects to `/accounts/login/`
  (connect default); `google_sub` nullable on legacy rows.
- [x] 5.4 backend: Verify —
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
  google_api accounts` and `python manage.py check` pass.
  No `openapi.json`/`api-types.ts` regen needed (no ninja
  ops changed).

## 6. Docs

- [x] 6.1 both: Update AGENTS.md — the `google_api/` row in
  the layout table and the "News digest → Google task" config
  note to mention `/google/signin/` (Google sign-in +
  optional tasks scope) and the `google_sub` column; update
  `.env.example`'s Google block to mention the sign-in flow
  and the consent-screen scope list.

## Workflow follow-up

- Maintainer adds `openid`, `userinfo.email`,
  `userinfo.profile` to the `django-apps-7345` OAuth consent
  screen in GCP Console (non-sensitive scopes; `auth/tasks`
  already present). No new redirect URI needed.
- Maintainer applies `google_api` migration to prod manually:
  `python manage.py migrate` with the prod `DATABASE_URL`.
- Archive the change after merge.

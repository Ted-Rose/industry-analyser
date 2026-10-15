# Industry Analyser — React + Vite Frontend Migration Plan

> **Status**: Plan. Blueprinted from the completed migration in the
> sibling project `django-apps` (`~/personal_data/p_projects/django-apps`),
> where `google_tasks` (`/tasks/`) and `finance` (`/finance/`) are fully
> cut over to React SPAs on the same Django backend. Reference docs there:
> `docs/plans/NEW_APP_REACT_GUIDELINES.md` (canonical playbook) and
> `docs/plans/DJANGO_APPS_REACT_REWRITE.md` (platform-level notes).
> A "Known pitfalls" section at the bottom is filled in from the
> bug-fix history of that migration — read it before implementing.

## 1. How django-apps did it (the proven architecture)

Django stays the backend; each app's UI becomes a **Vite entry** in a
shared `frontend/` workspace, mounted by a shared shell view, with all
data flowing through a shared **django-ninja** JSON API:

- `frontend/` — one Vite 5 + React 19 + TypeScript workspace at repo
  root. `vite.config.ts` has one `rollupOptions.input` per app
  (`src/tasks/main.tsx`, `src/finance/main.tsx`), builds to gitignored
  **`frontend_dist/`** at repo root with `manifest.json`,
  `base: '/static/'`.
- **`django-vite`** bridges the two: `{% vite_asset 'src/<entry>/main.tsx' %}`
  resolves hashed assets through `frontend_dist/manifest.json` in prod,
  or emits `http://localhost:<port>` dev-server URLs when
  `VITE_DEV=1`. `frontend_dist` is a `STATICFILES_DIRS` entry (filtered
  by `os.path.isdir` so a fresh checkout doesn't warn) → `collectstatic`
  ships the bundles; the manifest is read from disk at request time.
- **`spa_shell`** (`django_apps/views.py` + `templates/spa_shell.html`):
  one Django view renders `<div id="root">`, emits the vite asset tags,
  `@ensure_csrf_cookie`, and a `json_script` bootstrap payload
  (`{user}`). `react_app` wraps it: **GET/HEAD → shell, anything else →
  404** (mutations live under `/api/` only).
- **URL cutover pattern** (`finance/urls.py`): `partial(react_app,
  entry='<entry>', title='…')` mounted on `''` plus
  `path('<path:subpath>', …)` catch-all (no trailing slash — matches
  `x` and `x/` so no APPEND_SLASH hop). Named routes are **kept** so
  `reverse()`/`{% url %}` callers keep working. Legacy strangler mount
  `/<app>/app/*` 301-redirects via `app_redirect`.
- **API**: one `NinjaAPI` (`auth=django_auth` — session cookie + CSRF)
  at `/api/`; each app has `<app>/api.py` with a `Router`, mounted via
  `api.add_router('/<entry>/', …)`. Custom exception handlers emit a
  uniform `{error: slug, detail}` shape; 401s return JSON
  `{error: 'unauthenticated', login_url}` instead of redirecting.
- **Frontend conventions**: `main.tsx` (`createRoot` +
  `QueryClientProvider` + `BrowserRouter basename='/<entry>'`),
  `App.tsx` `<Routes>` table, `api.ts` typed fetchers over
  `shared/api/client.ts` (CSRF header injection, `redirect: 'manual'`,
  401 → navigate to `login_url`), `mutations.ts` (toast +
  `invalidateQueries`), `routes/` page components.
- **Types**: `manage.py export_openapi_schema` → committed
  `frontend/openapi.json` → `openapi-typescript` → per-entry
  `src/<entry>/api-types.ts` (committed, drift-checked).
- **Dev loop**: two processes — `VITE_DEV=1 python manage.py runserver`
  and `npm run dev --prefix frontend` (vite dev server on a
  **non-default port 5273** with `strictPort`), browse `:8000`. VS Code
  launches both via a `compounds` entry.
- **Deploy (GCP)**: multi-stage Dockerfile — `node:22-slim` stage runs
  `npm ci --include=dev && npm run build`, final python image copies
  only `frontend_dist/`; `collectstatic` at image build (needs
  build-time env vars for settings import).
- **Deploy (Vercel)**: `vercel.json` runs `@vercel/static-build`
  (`build_files.sh` → `distDir: staticfiles`) + `@vercel/python` on
  `wsgi.py` (`maxLambdaSize: 15mb`). `build_files.sh` builds a venv via
  `uv` (Vercel's system python is PEP 668 managed), runs
  `npm ci --include=dev` + `npm run build`, then **`rm -rf
  frontend/node_modules`** — required or the lambda exceeds
  `maxLambdaSize` — before `collectstatic`.

## 2. Industry-analyser scope

UI surfaces today (all function-based template views):

| App | Routes | Auth today | Verdict |
|---|---|---|---|
| `scrape_jobs` | `/` dashboard (job progress, day×job table) | `login_required` | **Convert** — real data UI; last stage (root mount) |
| `fetcher` | `/vacancies/` filtered vacancy list; `/add_keyword/` password-gated form; `/fetcher/` **GET-triggered full scrape** (legacy, blocking) | public / hardcoded password | **Convert** `/vacancies/` + keyword add; **remove** `/fetcher/` scrape view (use `manage.py scrape_vacancies`) |
| `classified_ads` | `/classified-ads/` — index, 6 ads tables, region stats/children/ads lists, daily sightings report, property list/detail, 2 region config POST forms | public | **Convert** — largest surface (~20 routes) |
| `tv_programs` | `/tv/` program list, `/tv/spoki-page/` | public | **Convert** — small |
| `accounts` | `/accounts/` static stub page | public | **Delete or redirect** to `/` — no content worth an entry |
| `blogs` | no views | — | Nothing to convert |
| `ai_providers` | Django admin + custom admin pages only | admin | **Out of scope** — admin stays Django |

PWA endpoints `manifest.json` + `sw.js` (`fetcher` views) **stay Django
views forever** — root scope and rendered `{% static %}` URLs are
load-bearing (same conclusion as django-apps).

### Decisions specific to this project

1. **Public pages need a public shell variant.** Most industry-analyser
   pages are public today; django-apps' `spa_shell` is
   `login_required`. Implement `_spa_shell`/`_react_app` undecorated
   cores with `react_app` (login-required) and `react_app_public`
   wrappers — django-apps' tv_archive plan introduces the same split.
   Public read endpoints get `auth=None` on their ninja ops;
   **mutations keep `django_auth`** (session). Default for ambiguous
   cases: match today's visibility (public stays public).
2. **`add_keyword`'s `HARD_CODED_PASSWORD` form becomes a session-auth
   API op** (`POST /api/vacancies/keywords/` → 401 JSON when logged
   out). This tightens auth slightly vs. today — acceptable, it's an
   admin action.
3. **Slug invariants** (one slug keys the vite input, manifest key,
   `entry=` arg, `src/<entry>/` folder, `/api/<entry>/` mount):
   - `fetcher` → entry `vacancies`, mount `/vacancies/`, API
     `/api/vacancies/`
   - `classified_ads` → entry `classified_ads` (`SPA_ENTRY_RE` is
     `[a-z0-9_]+` — hyphens illegal), public base `/classified-ads/`,
     API mount `/api/classified-ads/` (router mounts follow the public
     URL base so `spa_url_for`'s `/api/<x>/…` → `/<x>/…` rewrite for
     login `next` stays correct; entry slug and URL base may differ)
   - `tv_programs` → entry `tv`, mount `/tv/`, API `/api/tv/`
   - `scrape_jobs` → entry `dashboard`, mount `/`, API
     `/api/dashboard/` — root mount is the documented exception:
     `path('', …)` + a root `path('<path:subpath>', …)` must come
     **last** in `urlpatterns`, `BrowserRouter basename='/'`, and
     `spa_url_for` needs a `SPA_BASES`-style entry mapping
     `/api/dashboard/*` → `/`.
4. **Dev port: `5274`.** 5273 belongs to django-apps' vite; both
   projects may run on this machine simultaneously. Never the default
   5173 (shadowing bug — see pitfalls).

## 3. Stage 0 — platform plumbing (one PR)

### 3.1 Dependencies

`requirements.txt` (pin per repo convention):

```
django-vite==3.2.0
django-ninja==1.7.1
```

### 3.2 `industry_analyser/settings.py`

```python
INSTALLED_APPS += ['django_vite', 'ninja', 'industry_analyser']
# 'industry_analyser' must be in INSTALLED_APPS so APP_DIRS finds
# industry_analyser/templates/spa_shell.html (it's absent today).

# frontend_dist/ is generated at build time (gitignored) — filter by
# existence or `manage.py check` warns (staticfiles.W004) on fresh
# checkouts.
STATICFILES_DIRS = [
    p for p in (os.path.join(BASE_DIR, 'frontend_dist'),)
    if os.path.isdir(p)
]

# Vite emits base64url content hashes (contain - and _); the stock
# [0-9a-f] immutable test misses them → hashed assets get revalidated
# on every page load.
WHITENOISE_IMMUTABLE_FILE_TEST = r'\.[0-9A-Za-z_-]{8}\.'

DJANGO_VITE = {
    'default': {
        'dev_mode': DEBUG and os.environ.get('VITE_DEV') == '1',
        'dev_server_port': int(os.environ.get('VITE_PORT', '5274')),
        'static_url_prefix': '',
        'manifest_path': os.path.join(
            BASE_DIR, 'frontend_dist', 'manifest.json'
        ),
    }
}
```

Note: `env.db('DATABASE_URL')` already defaults `CONN_MAX_AGE` to 0 —
correct for Vercel serverless (no persistent connections); keep it.

### 3.3 `industry_analyser/views.py` — shared shell helpers

Port from `django_apps/views.py`: `SPA_ENTRY_RE`,
`_manifest_has_entry`, `_spa_shell` (undecorated core),
`spa_shell = login_required(ensure_csrf_cookie(_spa_shell))`,
`react_app` / `react_app_public` (GET/HEAD → shell else 404),
`app_redirect`. Bootstrap payload: `{'user': username or None}` — no
`user_language` here (no i18n in this project).

### 3.4 `industry_analyser/templates/spa_shell.html`

Copy `django_apps/templates/spa_shell.html`: `{% load django_vite %}`,
`{% vite_hmr_client %}`, `{% vite_react_refresh %}`, `{% vite_asset
vite_entry %}` behind `manifest_ready`, `<div id="root">`, bootstrap
`json_script`, and the "React entry not loaded" diagnostic when the
manifest is missing at runtime (renders a warning instead of a 500).
Keep the PWA `<link rel="manifest" href="/manifest.json">` + theme-color
meta from current templates in the shell head.

### 3.5 `industry_analyser/api.py` — shared NinjaAPI

Port `django_apps/api.py` minus the Google-reauth bits:
`NinjaAPI(auth=django_auth)` (also mount a second `NinjaAPI` for public
routers or use per-op `auth=None` — django-ninja op-level `auth`
overrides), exception handlers → uniform `{error, detail}` (401
`{error:'unauthenticated', login_url}`, 404, 422 validation, HttpError
slug map), `spa_url_for` + `SPA_BASES` for `/api/dashboard/` → `/`.

### 3.6 `frontend/` workspace

Copy structure from `django-apps/frontend/`:

- `package.json` — deps: `react`, `react-dom`, `react-router-dom`,
  `@tanstack/react-query`; devDeps: `vite`, `@vitejs/plugin-react`,
  `typescript`, `vitest`, `@testing-library/*`, `jsdom`,
  `openapi-typescript`, eslint/prettier (optional).
  Scripts: `dev`, `build` (`tsc --noEmit && vite build`), `typecheck`,
  `test`, `gen:types`.
- `vite.config.ts` — copy wholesale, changing only
  `rollupOptions.input` (entries per §2) and `server.port` default
  `5274`; keep `strictPort`, `base: '/static/'`,
  `outDir: '../frontend_dist'`, `manifest: 'manifest.json'`, the
  Django-proxy regex, output file naming.
- `src/shared/` — copy `api/client.ts` + `api/errors.ts` (CSRF
  injection, `redirect:'manual'`, opaqueredirect → login bounce,
  `ApiError`), `components/` (NavBar, Toasts, BurgerMenu… as needed),
  `hooks/useBootstrap.ts`, `queryClient.ts`. Drop `i18n.ts`/`locales`
  (no i18n here).
- `frontend/openapi.json` — generated by
  `python manage.py export_openapi_schema --output
  frontend/openapi.json` then `openapi-typescript` per entry
  (`gen:types`); **both are committed**; add a `printf '\n' >>` step so
  the committed file keeps its trailing newline (django-apps' CI
  diff-check expects it).
- `tsconfig.json`, `src/vite-env.d.ts`, `src/test/setup.ts`.

### 3.7 `.gitignore` / `.dockerignore`

Add `frontend_dist/`, `frontend/node_modules/` to `.gitignore`;
`frontend/node_modules`, `frontend_dist` to `.dockerignore` (the image
build produces its own).

### 3.8 `.vscode/launch.json`

Add alongside existing configs (copy django-apps' — same machine, same
nvm path works):

```jsonc
{
    "name": "Python Debugger: Django (VITE_DEV)",
    "type": "debugpy",
    "request": "launch",
    "program": "${workspaceFolder}/manage.py",
    "args": ["runserver"],
    "django": true,
    "justMyCode": false,
    "env": {"VITE_DEV": "1", "VITE_PORT": "5274"},
    "console": "integratedTerminal"
},
{
    "name": "Vite dev server",
    "type": "node",
    "request": "launch",
    "cwd": "${workspaceFolder}/frontend",
    "runtimeExecutable": "${env:HOME}/.nvm/versions/node/v22.2.0/bin/npm",
    "runtimeArgs": ["run", "dev"],
    "env": {
        "PATH": "${env:HOME}/.nvm/versions/node/v22.2.0/bin:${env:PATH}",
        "VITE_PORT": "5274"
    },
    "console": "integratedTerminal"
}
```

Plus compound `"Django + Vite"` running both. (Absolute nvm path is
required — VS Code launched from the Dock doesn't inherit the shell's
nvm PATH.) Browse `http://localhost:8000/` — Django serves the shell
and `{% vite_asset %}` emits `:5274` URLs in dev mode.

### 3.9 PWA hardening (do in stage 0, before any SPA ships)

`fetcher/templates/fetcher/sw.js` currently **caches every same-origin
GET**, which would cache `/api/*` JSON — add an `/api/` bypass
(network-only, never cache). Add a cache-version constant bumped on
every shipped frontend change, and **don't register the SW on
localhost** (it stale-serves vite dev modules). Serving `sw.js` and
`manifest.json` stays in Django views.

## 4. Per-app migration stages

Repeat per app (order: `vacancies` → `tv` → `classified_ads` →
`dashboard` — small to large; dashboard last because root mount). For
small apps the strangler mount may be skipped and cutover done
directly; for `classified_ads` keep the strangler stage.

**Migrations — go full-send locally.** The dev DB is the gitignored
SQLite `db.sqlite3`, so the implementing agent runs
`python manage.py makemigrations` **and** `migrate` freely — generate
and apply after every model change, no asking. Production is covered
by CI: a push to `master` that changes `migrations/` files triggers
`.github/workflows/run-migrations.yml`, which creates and executes a
`run-migrations` Cloud Run job (`python manage.py migrate`) against
the prod database. Committing the generated migration files is all
that's needed — never point a local `migrate` at the prod
`DATABASE_URL`.

1. **API router** — `<app>/api.py` `Router`; port each view's GET logic
   into ops returning ninja `Schema`s; POST forms become mutation ops
   returning `{'success', 'message'}`; mount
   `api.add_router('/<url-base>/', router)` in
   `industry_analyser/urls.py`; `path('api/', api.urls)` before app
   includes. Public reads: `auth=None`; mutations: `django_auth`.
   Few fat endpoints (one GET per page incl. filter option lists) —
   `CONN_MAX_AGE=0` on serverless makes granular per-widget calls the
   risk, not response size.
2. **Frontend entry** — `frontend/src/<entry>/`: `main.tsx`
   (`BrowserRouter basename='/<url-base>'`), `App.tsx` (`<Routes>`,
   `'/'` and `'*'` Navigate to default page), `api-types.ts`
   (generated), `api.ts`, `mutations.ts`, `routes/`, `components/`.
3. **Build wiring** — vite `input`, `gen:types` clause, regenerate
   `openapi.json` + `api-types.ts`, commit both.
4. **Strangler mount** (optional for small apps) — `/<base>/app/` serves
   `react_app[_public]` while templates still serve `/<base>/`.
5. **Cutover** — `/<base>/` + every named route becomes the shell
   partial; `/<base>/app/*` → `app_redirect` 301s; non-GET/HEAD under
   the base 404s; delete templates + any form-POST views; keep route
   `name=`s for `reverse()` callers.
6. **Tests** — Django `TestCase` on `/api/` URLs (unauthenticated
   behavior per auth choice, mutation shape, validation → 422);
   Vitest+RTL for pages with logic; optional Playwright smoke.
7. **Bump the SW cache version** in `sw.js`.

### Per-app notes

- **vacancies** (`/vacancies/`): filters (`include_keywords`,
  `exclude_keywords`, `include_industries`, `show_active_only`) become
  GET query params — keep them in the URL so pages stay bookmarkable;
  pagination via `?page=`. `/add_keyword/` → `POST
  /api/vacancies/keywords/`; 301 `/add_keyword/` → `/vacancies/keywords/`
  (or keep the named route serving the shell page). **Delete the
  `/fetcher/` GET-scrape view** — it blocks a request worker for a full
  scrape; `manage.py scrape_vacancies` + Cloud Run jobs already cover
  this.
- **tv** (`/tv/`): two pages; trivial.
- **classified_ads** (`/classified-ads/`): ~20 routes → ~10 SPA routes
  (apartments/houses × rent/sale tables are one parameterized
  component each; region stats + children + ads list similarly). The
  two region-config POST forms → `POST /api/classified-ads/regions/config/`
  mutations (`django_auth` — currently public; gating them is a small,
  deliberate tightening). Heavy server-side aggregates
  (`_compute_*_region_stats`) stay server-side — expose as fat GETs.
- **dashboard** (`/`): `login_required` → use `react_app` (not the
  public variant). Mount `path('', react_app_dashboard)` and the root
  `path('<path:subpath>', …)` **last** in `urlpatterns`; React Router
  `basename='/'`; add `SPA_BASES` entry `dashboard → '/'` for login
  `next` rewriting. Alternative, if root-mount risk isn't wanted: keep
  the template dashboard (it works, it's the PWA `start_url`, same
  reasoning django-apps used to keep `home` a template).

## 5. Deployment

### 5.1 GCP Cloud Run (primary)

`Dockerfile` — add a frontend stage and copy the output (mirrors
django-apps):

```dockerfile
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --include=dev   # devDeps needed even if NODE_ENV=production
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
# … existing steps …
COPY . .
COPY --from=frontend /frontend_dist /app/frontend_dist
# existing build-time env vars (SECRET_KEY, DATABASE_URL, …) are
# already required for settings import during collectstatic — keep them
RUN python manage.py collectstatic --noinput
```

`.github/workflows/deploy-web-service.yml` — add `'frontend/**'` to
`on.push.paths` so frontend-only changes deploy.

Production migrations need no work: `run-migrations.yml` already fires
after the scraper-jobs deploy on `master` (or via `workflow_dispatch`)
and runs `python manage.py migrate` in a `run-migrations` Cloud Run
job. (The django-apps audit flags ephemeral migrate jobs as flaky —
they moved `migrate` onto the CI runner — but this project's
`run-migrations` job is established and working; keep it unless it
proves flaky.)

### 5.2 Vercel (secondary — being debugged, but write for it)

Target `vercel.json` (the django-apps shape, verified live):

```json
{
  "version": 2,
  "builds": [
    {"src": "build_files.sh", "use": "@vercel/static-build",
     "config": {"distDir": "staticfiles"}},
    {"src": "industry_analyser/wsgi.py", "use": "@vercel/python",
     "config": {"maxLambdaSize": "15mb", "runtime": "python3.12"}}
  ],
  "routes": [
    {"src": "/static/(.*)", "dest": "static/$1"},
    {"src": "/(.*)", "dest": "industry_analyser/wsgi.py"}
  ]
}
```

`build_files.sh` — add the frontend build between env setup and
collectstatic (keep the existing migrate/scrape steps as-is for now;
they're current deploy behavior):

```bash
if command -v uv >/dev/null 2>&1; then   # PEP 668: venv required
  uv venv --python 3.12 /tmp/build-venv
  source /tmp/build-venv/bin/activate
  uv pip install -r requirements.txt
else
  python3 -m venv /tmp/build-venv && source /tmp/build-venv/bin/activate
  python3 -m pip install -r requirements.txt
fi
python3 industry_analyser/console_tasks/build.py
npm ci --prefix frontend --include=dev
npm run build --prefix frontend
rm -rf frontend/node_modules   # else lambda exceeds 15mb maxLambdaSize
python3 manage.py collectstatic --noinput
mkdir -p .vercel/output/static
cp -r staticfiles/* .vercel/output/static/
```

`frontend_dist/` must be **present in the lambda bundle at runtime**
(django-vite reads `manifest.json` from disk), not only shipped to the
static CDN — it is, because `@vercel/python` bundles repo files, but
verify after the next `.vercelignore`/include changes. Vercel env vars
must provide `SECRET_KEY`/`DATABASE_URL`/`DB_SSL_CERT` — settings have
no defaults.

## 6. Verification checklist (per stage)

```bash
source venv/bin/activate
python manage.py makemigrations && python manage.py migrate  # local
                                                             # sqlite — free to run
python manage.py check
python manage.py test <app>
npm run typecheck --prefix frontend && npm test --prefix frontend
python manage.py export_openapi_schema --output frontend/openapi.json \
    && printf '\n' >> frontend/openapi.json \
    && npm run gen:types --prefix frontend
npm run build --prefix frontend   # manifest gains the entry key
```

Manual: `VITE_DEV=1` runserver + vite dev server, browse
`http://localhost:8000/<base>/` — page renders via HMR; a mutation
succeeds; a deep link loads directly; unauthenticated API call returns
the expected 401/200; prod-mode (`npm run build`, no VITE_DEV) serves
hashed assets via whitenoise.

## 7. Known pitfalls (from the django-apps migration bug history)

Seed list — expanded by git-history audit (see below):

- **Vite port shadowing**: default 5173 gets stolen by another
  project's vite → page stuck on "Loading React app…". Fixed in
  django-apps by moving to 5273 + `strictPort` + plumbing `VITE_PORT`
  through settings and launch.json. We use **5274** here.
- **Lambda size**: `frontend/node_modules` bundled into the Vercel
  lambda → exceeds `maxLambdaSize`; must `rm -rf` it in
  `build_files.sh` after the build.
- **PEP 668**: Vercel's uv-managed python refuses `pip install` into
  system env → build inside `/tmp/build-venv`.
- **`npm ci` skipping devDeps** when `NODE_ENV=production` → vite/tsc
  missing → always `npm ci --include=dev`.
- **Whitenoise hash regex**: `[0-9a-f]` doesn't match Vite's base64url
  hashes (`-`, `_`) → immutable-cache misses; use
  `WHITENOISE_IMMUTABLE_FILE_TEST = r'\.[0-9A-Za-z_-]{8}\.'`.
- **Missing manifest at runtime** → `DjangoViteAssetNotFoundError`
  (500); `manifest_ready` gate renders a diagnostic instead.
- **Trailing-slash hops**: `path('<path:subpath>')` (no slash) matches
  both `x` and `x/` — avoids APPEND_SLASH redirects breaking client
  routes.
- **Non-GET methods on retired form-POST URLs** must 404, not render
  the shell.
- **`fetch` following redirects**: `redirect: 'manual'` + opaque-
  redirect → navigate to login; never let XHR follow to login pages.
- **SW caching `/api/`**: industry-analyser's current `sw.js` caches
  all same-origin GETs — must bypass `/api/` before SPAs ship.
- **`SPA_ENTRY_RE`** restricts entry names to `[a-z0-9_]+` — the
  hyphenated `/classified-ads/` URL needs entry `classified_ads` +
  hyphenated API mount.

### 7.1 Bug history from the django-apps migration

Audited from `git log` on `main` (React era starts at `8ac062a`, the
Vercel bring-up just before it, through `8dfab0e`). Fixing-commit shas
in parentheses for traceability.

#### Dev workflow / local dev loop

- **Vite port shadowing, IPv6 twist** — SPA stuck on "Loading React
  app…" → another project's vite owned `*:5173`; `localhost` resolved
  to `::1` first so module requests got that server's HTML fallback →
  moved to :5273 via `VITE_PORT` (read by both `vite.config.ts
  server.port` and `DJANGO_VITE.dev_server_port`) plus `strictPort`
  so a collision fails loudly (dd5192e).
- **Service worker vs HMR** — vite dev modules always rendered one
  reload stale → the PWA worker's stale-while-revalidate on `/static/`
  cached dev-server responses → unregister the SW and delete its
  caches when `location.hostname` is localhost/127.0.0.1/[::1]
  (92c9315).
- **Dev-proxy allowlist too broad** — real Django static files broke
  through the vite dev server → the proxy exempted all of `/static/`,
  but vite emits dev URLs like `/static/src/*` and `/static/@*` →
  keep only Vite-internal paths (`/@*`, `/src/`, `/node_modules/`,
  incl. under `/static/`) local; proxy everything else to :8000
  (fb0ab70).
- **VS Code can't spawn npm** — the "npm run dev" launch config died
  silently → Dock-launched VS Code doesn't inherit the shell's nvm
  PATH → point `runtimeExecutable` at the absolute nvm npm and prepend
  its dir via `env` (3e74782).
- **`vite/modulepreload-polyfill` flagged by TS** — red squiggles on
  the `main.tsx` side-effect import → vite's virtual module ships no
  types → declare it in a `*.d.ts` (a2b025a). Also: Chrome DevTools
  probes `.well-known/appspecific/com.chrome.devtools.json` on every
  load → answer with an empty JsonResponse when DEBUG to keep 404
  WARNING noise out of runserver logs (23beb15).

#### django-vite plumbing

- **Manifest gate was wrong both ways** — `VITE_DEV=1` shells showed
  the "manifest missing" diagnostic, and a stale manifest lacking the
  entry key 500'd in `{% vite_asset %}` → `manifest_ready` must be
  `dev_mode OR manifest.json contains the entry key` (a corrupt
  manifest degrades to the warning too), not `os.path.exists`
  (fb0ab70). The seed entry covers the 500; the non-obvious part is
  that *dev mode must bypass the manifest check entirely* — vite dev
  never writes one.
- **`STATICFILES_DIRS` warning on fresh checkout** — `frontend_dist/`
  is gitignored so `manage.py check` emitted `staticfiles.W004`
  forever → filter the list to dirs that exist (fb0ab70).

#### Routing & URLs

- **Cutover contract details** (8472567, 9788cfb): besides the
  no-trailing-slash catch-all and non-GET→404 already seeded —
  - keep `path('', react_app, name='<old-index-name>')` so
    `reverse('app:dashboard')` still resolves for `home.html` links
    and the OAuth default redirect;
  - add a *bare* `path('app', app_redirect)` alongside `app/` and
    `app/<path:subpath>` 301s — without it, `/tasks/app` (no slash)
    falls through to the catch-all and renders a second shell;
  - normalize pre-cutover paths stored in `localStorage`
    (`lastTasksView`, referrer): `spaPathFromStoredUrl` maps legacy
    `/app/*` onto the new basename before handing to the router;
  - `BrowserRouter basename` moves from `/tasks/app` to `/tasks` at
    cutover — old template URLs resolve only because the React route
    names mirror the template URL names. Plan client routes to match.
- **`login_url`/`next` pointed at JSON** — 401s from `/api/<app>/…`
  sent users back to a raw JSON URL after login → `spa_url_for()`
  maps `/api/<app>/<sub>` onto the SPA page (and remapped `/app/*` →
  `/<app>/*` at cutover); `next` must be `urlencode`d (0f5b1ba,
  8472567).
- **Externally baked-in URLs can't move** — `requisition_callback`
  stayed a Django view after the finance cutover because the URL is
  embedded in live GoCardless requisitions → inventory every URL
  referenced by third parties/emails/bookmarks before deleting routes
  (9788cfb).
- **Login required on the shell itself** — mount `@login_required`
  directly on `react_app` (not just inner data endpoints) so the
  catch-all can't serve the shell to anonymous users (fb0ab70).

#### Auth & CSRF

- **Session-expired 30x surfaces as `opaqueredirect`** — seeded, with
  the extra detail that it also fires on APPEND_SLASH and middleware
  redirects, not just login; the client navigates to
  `/admin/login/?next=<current path>` and returns a never-resolving
  promise so callers don't catch a bogus status-0 ApiError (4d7db72).
- **Public `/api/docs` + `openapi.json`** — ninja's default docs
  exposed the whole schema → `docs_decorator=staff_member_required`;
  the committed `frontend/openapi.json` + `export_openapi_schema`
  workflow makes served-docs access unnecessary (0f5b1ba).
- **BOLA via `label_ids`** — a mutation could reference another
  user's labels by id → scope every `get_object_or_404`/FK-id check
  by `request.user`; regression-tested (0f5b1ba).
- **Body heuristic mangled BodyInit** — an allowlist
  (`FormData`/`Blob`/`ArrayBuffer`/`URLSearchParams` exempt from
  JSON.stringify) still encoded TypedArrays/ReadableStreams → invert:
  JSON-encode only plain objects and arrays, pass every real
  `BodyInit` through so fetch sets Content-Type itself (4d7db72).

#### PWA & service worker

- **Navigation fetch + `opaqueredirect`** — SW `fetch(req)` on
  navigations uses redirect mode `manual`; a redirecting response
  (bank-callback 302, session-expiry → login) arrived status-0 with
  possibly no URL, and `new URL(res.url)` threw — killing the whole
  navigation → pass `opaqueredirect` responses through untouched (the
  browser re-navigates) and cache under `res.url || req.url`
  (107f3f7).
- **Cache-first navigations served stale pages** — after
  POST-redirect-GET the SW replayed the pre-POST HTML → switch
  navigations to network-first, cache only `res.ok` pages that didn't
  land inside a bypassed path, fall back to cache then offline page
  (9699183).
- **Add `/api` to `BYPASS_PATHS`** — the moment the SPA shipped, the
  SW could serve cached API JSON; bump `PWA_CACHE_VERSION` on every
  SPA-shipping commit to force clients off the old worker (8472567,
  a2b025a, 9788cfb).

#### Vercel & Docker deploys

- **Vite 8 vs build-image Node** — first preview deploy failed: Vite
  8 needs Node ^20.19/>=22.12 but Vercel takes Node from *project
  settings* → downgrade to Vite 5 + plugin-react 4 (any Node ≥18) or
  pin the project's Node version explicitly (8ba35e1).
- **`uv venv` picked CPython 3.14** — no psycopg2-binary wheel and
  Django 4.2 doesn't support it → `uv venv --python 3.12` to match
  the lambda runtime declared in `vercel.json` (0a08707).
- **`routes` + `headers` are mutually exclusive** — adding an
  immutable-Cache-Control `headers` block to the legacy
  `builds`+`routes` schema failed config validation on *every*
  production deploy → drop it; the CDN serves `/static/*` via the
  routes mapping anyway and Cloud Run covers immutability via
  `WHITENOISE_IMMUTABLE_FILE_TEST` (60ef3e8).
- **"Hardened" build script re-broke prod** — gating `rm -rf
  frontend/node_modules` on `$VERCEL` and widening `.vercelignore`
  (secrets, `staticfiles/`, `docs/`) kept prod deploys red: if the
  build env doesn't expose `VERCEL` the ~67 MB dir re-enters the
  lambda, and `staticfiles/` risks filtering the declared `distDir`
  → when prod is broken and logs are invisible, restore the last-green
  files byte-for-byte (6cab27e).
- **`collectstatic || true` shipped a CSS-less site** — the Docker
  build had no `private_settings.json`, so collectstatic silently
  failed and `CompressedManifestStaticFilesStorage` 500'd every
  `{% static %}` → generate a build-time dummy settings file, drop
  `|| true`, keep the step strict (a6b16cb, 96a322e).
- **Serverless + `CONN_MAX_AGE`** — each lambda holding pooled
  connections exhausted the DB's `max_connections` ("remaining
  connection slots are reserved…") → `CONN_MAX_AGE=0` on Vercel,
  pooling only on long-lived Cloud Run workers (6ec1305).
- **Per-host DB settings drift** — `DATABASE_URL` query params need to
  reach `sslmode` (use `setdefault`, don't overwrite), and a `capem`
  env var can contain a multi-cert bundle needing regex re-wrapping,
  not a string replace (ba85a12, de54819).
- **Ephemeral migrate job was the flaky part** — a per-deploy
  `django-migrate-<sha>` Cloud Run job added ~1 min of orchestration
  and surfaced `sslmode=verify-full`/`root.crt` failures → run
  `migrate` on the CI runner (already WIF-authed; secrets pulled from
  Secret Manager in-step) before the rollout (f56d7fa).
- **Spike the deploy pipeline first** — before building any SPA UI, a
  throwaway shell PR verified that `frontend_dist/manifest.json`
  lands inside the `@vercel/python` lambda so `{% vite_asset %}`
  resolves there (8ac062a, 690e857). Do the same here.

#### API contract & parity regressions

- **Required body that the SPA doesn't send** — `POST
  /transactions/sync/` 422'd whenever no account filter was set: ninja
  demanded a `SyncIn` body but the SPA POSTs bare → make payloads
  `Optional[…] = None` wherever the old form view had no body
  contract, and add a no-body regression test (8bd6b1a).
- **Uniform error shape incl. 422** — ninja's default `ValidationError`
  response broke the `{error, detail}` contract → add a
  `ValidationError` exception handler emitting
  `{error: 'validation_error', detail: …}` (0f5b1ba).
- **`2xx {success: false}` mapped to 400** — a delegated view that
  fails with HTTP 200 + `success:false` was surfaced as a misleading
  client error → the adapter maps it to 500 so the SPA shows failure,
  not "bad request" (0f5b1ba).
- **Declared-but-dead sort options** — the API accepted
  `due_asc`/`due_desc` but never implemented them → silently wrong
  ordering; audit every declared enum/param for a real code path
  (160ee95).
- **Template-vs-SPA parity drift** — order badges numbered filtered
  rows while the template's `forloop.counter` never renumbered;
  divider cards vanished under the client-side label filter though
  the template kept them; the archived bucket got completed-*
  ordering; trash label counts ignored `?label=` → port *behavior*,
  not just markup; diff-test against the template views before
  deleting them (160ee95, 0f5b1ba).
- **Optimistic-update insertion order** — uncompleting a task
  unshifted it to the top instead of its ordered position → recompute
  the insertion index from the active ordering; refetch corrects but
  the flash is visible (0314f1c).
- **Aggregate sync result hid failures** — one aggregate count made
  "nothing new", "skipped (non-LN requisition)" and "upstream failed"
  indistinguishable for shared-accounts users → return a per-account
  outcome list and toast the breakdown (b9082ab). Same class: one bad
  hashtag aborted label processing for *all* tasks and `sync_view`
  swallowed it → make failures per-item non-fatal and report them in
  the response stats (7c5369a).
- **Schema/type drift** — `TaskOut` was missing `deleted_at` until
  review caught it → CI regenerates `frontend/openapi.json` via
  `manage.py export_openapi_schema`, diffs it, and porcelain-checks
  `api-types.ts` so stale or untracked generated types fail the build
  (0f5b1ba, 4d7db72).
- **Mirror input bounds in the schema** — views had caps
  (`REORDER_CAP=500`, label_ids ≤ 50, query `max_length`) the ninja
  schemas didn't → declare them with `Field(max_length=…)`/`Query` so
  oversized payloads 422 at the boundary instead of 400 deep in the
  view (0f5b1ba).
- **Keep mutation logic in the views, delegate from ninja** — ~18
  google_tasks mutations stayed in `views.py` with the API delegating
  verbatim, which kept tests patching `views.*` valid and minimized
  behavioral risk; finance instead reimplemented mutations against
  the same forms/services — either works, but pick one pattern per
  app and keep response wording identical to the old `messages`
  strings (8472567, 3a6aa3d).

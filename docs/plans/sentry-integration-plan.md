# Sentry integration — industry-analyser

Status: implemented — Sentry provisioning DONE 2026-10-28; code
  landed on `feat/sentry-integration` (backend DSN-gated init,
  ninja exception handler, spa-bootstrap web config, capture
  helpers wired into run_all_jobs/core_scraper/ai_providers;
  frontend initSentry + ErrorBoundary on all 5 entries).
  Org `industry-analyser-ue` (EU, de.sentry.io) holds
  `industry-analyser-api` + `industry-analyser-web` with DSNs,
  web inbound filters, org data-scrubbing and production
  level:error email workflows. Key rate-limit calls no-op on
  this org (the `rate-limits` project feature isn't enabled on
  new-org plans — acceptable, revisit if quota pressure shows).
  `env-file` secret in `gen-lang-client-0833674612` carries the
  EU DSNs (version 3), live at next deploy — Sentry stays
  inactive until then (both DSNs empty locally).
Date: 2026-10-28
Standard: `Bible Research/docs/plans/sentry-integration-standard.md`
Reviewed-by: independent repo audit 2026-10-28 — corrections
  folded in (ninja re-raise semantics, DOM-level bootstrap read,
  Vercel-is-legacy caveat, committed frontend_dist step).

## What this is

Add DSN-gated Sentry monitoring to this repo's deployables,
following the workspace playbook. One Django 5.2 monolith serving
its own Vite SPAs via django-vite + `spa_shell`, deployed to:

- GCP Cloud Run — `industry-analyser` web service + ~10
  scheduled scrape jobs (project `gen-lang-client-0833674612`),
  via `.github/workflows/` + Dockerfile. Staging/PR services
  (`industry-analyser-pr-<n>`/`-staging`) share `env-file` — set
  `SENTRY_ENVIRONMENT=staging`/`preview` there.
- Vercel — `api/index.py` file-based function. **Likely a
  retired vestige** (AGENTS.md "Known gaps" lists `vercel.json`,
  `build_files.sh`, `cloudbuild.yaml` as legacy; the live
  pipeline is workflows + Dockerfile). The plumbing still works,
  but treat Vercel env wiring as OPTIONAL — verify the project
  is still connected before bothering.
- GCP Monitoring alert policies (`terraform/monitoring.tf`)
  already email on job failures — Sentry's `internal_error`
  stream will overlap; decide which is canonical (recommend:
  Sentry for stack context, Monitoring for infra).

Sentry org: **`industry-analyser-ue`** (EU, de.sentry.io — one
org per product; the clean `industry-analyser` slug was taken by
a US org created during provisioning). Projects:

- `industry-analyser-api` — platform `python-django`.
- `industry-analyser-web` — platform `javascript-react`.

Environment tag: `SENTRY_ENVIRONMENT` (explicit override) →
`VERCEL_ENV` → `production` when `K_SERVICE` is set (Cloud Run
service AND jobs) → `development`.
Release: `K_REVISION` → `VERCEL_GIT_COMMIT_SHA` → unset locally.

## Provisioning (Sentry REST API)

DONE 2026-10-28 — recorded for repeatability. Org
`industry-analyser-ue` was created by the user in the Sentry web
UI (EU region picker — the API only creates US orgs); team slug
`industry-analyser`. Token:
`source ~/.config/devin/sentry.env` (SENTRY_API_TOKEN).

```bash
BASE="https://de.sentry.io/api/0"
AUTH="Authorization: Bearer $SENTRY_API_TOKEN"
ORG="industry-analyser-ue"; TEAM="industry-analyser"

for spec in "industry-analyser-api:python-django" \
            "industry-analyser-web:javascript-react"; do
  name="${spec%%:*}"; platform="${spec##*:}"
  curl -s -X POST -H "$AUTH" -H 'Content-Type: application/json' \
    -d "{\"name\":\"$name\",\"platform\":\"$platform\"}" \
    "$BASE/teams/$ORG/$TEAM/projects/"
done
curl -s -H "$AUTH" "$BASE/projects/$ORG/industry-analyser-api/keys/"
curl -s -H "$AUTH" "$BASE/projects/$ORG/industry-analyser-web/keys/"

# DSN abuse protection (NESTED object — flat fields silently no-op):
curl -s -X PUT -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"rateLimit":{"window":3600,"count":100}}' \
  "$BASE/projects/$ORG/industry-analyser-web/keys/<key_id>/"
# ...repeat for the api key

# Web inbound filters (api project: leave web-noise filters OFF):
for f in browser-extensions web-crawlers legacy-browsers localhost; do
  curl -s -X PUT -H "$AUTH" -H 'Content-Type: application/json' \
    -d '{"active":true}' \
    "$BASE/projects/$ORG/industry-analyser-web/filters/$f/"
done

# Org-level scrubbing (replicate the bible-research settings):
curl -s -X PUT -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"dataScrubber":true,"sensitiveFields":["password","token",
  "authorization","api_key","secret","access_token",
  "refresh_token","session","csrftoken"]}' \
  "$BASE/organizations/$ORG/"

# Alert: POST $BASE/organizations/$ORG/workflows/ — triggers
# first_seen_event + regression_event (each "conditionResult":true);
# actionFilters logic "all" with tagged_event conditions
# (environment eq production, level eq error); action "email" /
# "issue_owners"; config {"frequency":30}; detectorIds=[<project's
# auto "Issue Stream" detector — GET .../detectors/>].
# Verified working payload on 2026-10-28.
```

Note: key `rateLimit` PUTs silently no-op on this org — the
`rate-limits` feature flag is not enabled on new-org plans
(checked via GET .../projects/.../features/). DSN abuse is still
bounded by the inbound filters and the free-tier quota drop.

## Secret wiring (zero build plumbing)

The SPA is server-rendered, so the web DSN ships inside the
existing `spa-bootstrap` json_script at request time — no vite
env vars, no Docker build args, no Vercel `VITE_*` vars.

- Cloud Run: replace the two lines in the `env-file` secret
  payload in `gen-lang-client-0833674612` (mounted as `DOTENV`
  for the web service AND every scheduled job — one update
  covers all entry points):

  ```bash
  gcloud secrets versions access latest --secret=env-file \
    --project=gen-lang-client-0833674612 > /tmp/env-file
  # replace the SENTRY_DSN=/SENTRY_WEB_DSN= lines added
  # 2026-10-28 (they hold the parked projects' DSNs)
  gcloud secrets versions add env-file \
    --project=gen-lang-client-0833674612 --data-file=/tmp/env-file
  ```

  New revisions take effect at the next deploy/revision.
- Vercel project env vars (only if the deploy is verified live):
  `SENTRY_DSN`, `SENTRY_WEB_DSN`, Production scope.
- Local `.env`: both lines present and EMPTY (added 2026-10-28).
- `.env.example`: add both keys (commented/empty) — committed doc.

## Backend changes

- `requirements.txt`: pin `sentry-sdk` (canonical dep file —
  bible_research uses `sentry-sdk==2.73.0`).
- New `industry_analyser/sentry.py` (mirror
  `bible_research/bible_research/utils.py`):
  - `sentry_before_send` — strip `request.data` on credential
    paths (`/admin/` — admin login posts passwords; receipts
    IMAP/Gmail-touching POST bodies); guard non-dict `request`.
  - `capture_internal_exception(exc)` — `new_scope()`, tag
    `error_code:internal_error`, level error.
  - `capture_provider_exception(exc, error_code)` — level
    warning, allowlist `{rate_limited, provider_error}` — for
    portal HTTP 429/5xx scraper failures and Gemini/OpenRouter
    failures in `ai_providers`; expected outcomes never sent.
- `industry_analyser/settings.py` (after `_load_env_file()`):
  `SENTRY_DSN = env('SENTRY_DSN', default='')` + `SENTRY_WEB_DSN`
  the same way; `if SENTRY_DSN: sentry_sdk.init(...)` —
  `DjangoIntegration()`, `LoggingIntegration(level=logging.INFO,
  event_level=None)` (**add `import logging`** — not imported
  today), `send_default_pii=False`, `before_send`, `environment`,
  `release=os.environ.get('K_REVISION') or
  os.environ.get('VERCEL_GIT_COMMIT_SHA')`,
  `traces_sample_rate=0.1`.
- `industry_analyser/api.py` — add
  `@api.exception_handler(Exception)` →
  `capture_internal_exception` + uniform `{error:'server_error',
  detail:'Internal Server Error'}` 500. Corrected rationale:
  django-ninja 1.7.1 RE-RAISES unhandled exceptions under
  `DEBUG=False`, so they already reach `DjangoIntegration` —
  the handler buys the uniform JSON body + the `internal_error`
  tag (and once it exists, capture depends solely on
  `capture_internal_exception`).
- `industry_analyser/views.py` `_spa_shell`: add to `bootstrap` —
  `'sentry': {'dsn': SENTRY_WEB_DSN, 'environment': ...,
  'release': ...}`. Both `spa_shell` and `spa_shell_public` flow
  through `_spa_shell`, and every vite entry's mount goes through
  them (dashboard/vacancies/companies/tv/receipts/classified-ads
  verified against `urls.py`); `bootstrap` currently carries only
  `user`.
- Scraper catch sites: `scrape_jobs/management/commands/
  run_all_jobs.py` (~line 218, the `(Exception, SystemExit)`
  catch) and `core_scraper` command wrappers →
  `capture_internal_exception`; upstream portal/AI failures →
  `capture_provider_exception` at warning.
- No CORS work: `corsheaders` is not installed and the SPA is
  same-origin.

## Frontend changes

- `frontend/`: `npm i @sentry/react`. `@sentry/vite-plugin`
  optional — skip sourcemap upload in v1.
- `frontend/src/shared/sentry.ts`: `initSentry()` — read
  `dsn/environment/release` from the `#spa-bootstrap` DOM node
  DIRECTLY (`useBootstrap` is a hook — can't run before
  `createRoot`); `import.meta.env.VITE_SENTRY_DSN` override for
  playbook parity. `browserTracingIntegration` +
  `replayIntegration({maskAllText, blockAllMedia})`;
  `replaysSessionSampleRate:0`, `replaysOnErrorSampleRate:1.0`,
  `tracesSampleRate:0.1`, `tracePropagationTargets:
  [location.origin]`.
  `beforeSend` drop list: `AbortError` (Error OR DOMException),
  `ChunkLoadError`/`Loading chunk \d+ failed`/`Loading CSS chunk`
  (match `event.message` + `exception.values[0].value` — stale
  tabs after a deploy hit message-only onerror events),
  `ResizeObserver loop`; `TypeError` network failures tagged
  `errorKind:network`, not dropped. Re-apply `context` on
  `onunhandledrejection`.
- `frontend/src/shared/errorReporter.ts` + `ErrorBoundary.tsx`
  (port `reactive-bible/src/utils/errorReporter.tsx`, adapt to
  `shared/toasts.ts`): window `error` + `unhandledrejection`;
  resource-load → `captureMessage` warning,
  `reportType:resource-load`, query string stripped, per-URL
  dedup.
- Each `src/<entry>/main.tsx` (vacancies, tv, classified_ads,
  dashboard, receipts): `initSentry()` +
  `initGlobalErrorHandlers()` before `createRoot`;
  `<ErrorBoundary>` around `<App/>`.
- **`frontend_dist/` is committed** (AGENTS.md: it ships the built
  SPA for local non-dev runs): after the code lands,
  `npm run build --prefix frontend` and recommit `frontend_dist/`
  in the same PR — Cloud Run rebuilds in Docker anyway, but the
  committed bundle must not go stale.
- Service worker (`fetcher/templates/fetcher/sw.js`,
  stale-while-revalidates `/static/`): extra resource-load
  warnings possible — handled by the warning stream; Sentry
  ingest is cross-origin, unaffected.
- Coverage caveat: Django admin + non-SPA pages get no web-SDK
  coverage — accepted.

## Event-stream contract (document in AGENTS.md)

`is:unresolved level:error environment:production` = agent-fixable
bugs only:

| Stream | Transport | Level | Tag |
|---|---|---|---|
| Unhandled 500s | DjangoIntegration | error | — |
| Caught API/job bugs | capture_internal_exception | error |
  `error_code:internal_error` |
| Browser exceptions | captureException | error | — |
| Scraper/AI upstream | capture_provider_exception | warning |
  `error_code:{rate_limited,provider_error}` |
| Resource loads | captureMessage | warning |
  `reportType:resource-load` |

Logs are breadcrumbs only (`event_level=None`) — the per-app
loggers emit a lot of DEBUG/INFO; none become events.

## Verification

- `python manage.py check`;
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test <app>`;
  frontend `npm run typecheck && npm test` (port a `sentry.test.ts`
  for the beforeSend list). No OpenAPI drift — exception handlers
  don't change the schema.
- No DSN → all capture calls no-op (assert in a test).
- After deploy: `GET .../industry-analyser-api/issues/` shows a
  real event; the SPA `spa-bootstrap` JSON carries `sentry.dsn`.
- Phase 2: port `.devin/skills/fix-sentry-issue-*` from Bible
  Research adapted to this repo's queues.

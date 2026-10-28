---
name: fix-sentry-issue-frontend
description: Pull unresolved production errors from the Sentry
  industry-analyser-web project, reproduce and fix them on a
  branch cut from master, open a draft PR, and mark the Sentry
  issue resolved only after the PR merges. Invoke when the user
  asks to fix Sentry issues / triage the Sentry queue in
  industry-analyser.
---

# Fix an unresolved Sentry issue (industry-analyser-web)

Target repo: this one — `Ted-Rose/industry-analyser` (remote
`origin`, the user's own repo, not a fork; default branch
`master`). The Sentry project is `industry-analyser-web` in org
`industry-analyser-ue`, hosted in the **EU region —
`https://de.sentry.io`**, NOT sentry.io.

## 0. Auth — required before anything else

    source ~/.config/devin/sentry.env   # provides SENTRY_API_TOKEN

The token is a user-level auth token shared across the user's
Sentry orgs. If `SENTRY_API_TOKEN` is unset, STOP and tell the
user to set it up once:

1. de.sentry.io → User Settings → Auth Tokens → Create New Token
   (or an org internal integration scoped to
   `industry-analyser-ue`).
2. Permissions: `Issue & Event: Read & Write`, `Project: Read`,
   `Release: Read`, `Organization: Read`. Save, copy the token.
3. `echo 'SENTRY_API_TOKEN=<token>' >> ~/.config/devin/sentry.env`

API helpers used throughout:

    BASE="https://de.sentry.io/api/0"
    AUTH="Authorization: Bearer $SENTRY_API_TOKEN"
    ORG="industry-analyser-ue"
    PROJECT="industry-analyser-web"

REST curl is unaffected by the machine's Netskope
TLS-intercepting proxy — the silent-failure quirk in `AGENTS.md`
applies only to the Python SDK's egress.

## 1. Fetch the work queue

    curl -s -H "$AUTH" \
      "$BASE/projects/$ORG/$PROJECT/issues/\
?query=is:unresolved+level:error+environment:production\
&statsPeriod=14d&sort=freq"

Only `level:error` browser exceptions are auto-fixable — that
filter IS the queue. Warning-level streams (`reportType:
resource-load`, `error_code:rate_limited` / `provider_error`)
are intentionally excluded, and backend errors live in the
sibling `industry-analyser-api` project — both out of scope
(see `AGENTS.md` "Sentry event streams").

## 2. Pick and analyze one item

- Default: ONE item per run — the highest-count/recent issue.
  If the user said "fix all", enumerate first and post the list.
- Fetch `GET $BASE/issues/<id>/events/latest/` — exception type,
  sourcemapped stack frames (file/line/function), tags, release
  sha (`K_REVISION`/`VERCEL_GIT_COMMIT_SHA`), breadcrumbs.
- Reproduce before fixing. Can't reproduce → report back to the
  user and move on; NEVER a speculative fix.

## 3. Decide where the fix belongs

Single repo, two stacks: a web-project error can still be a
backend bug — a django-ninja contract change or a failing
`/api/<entry>/` endpoint in `fetcher/`, `classified_ads/`,
`blogs/`, `tv_programs/`, `scrape_jobs/`, `ai_providers/`. If the
root cause is backend, fix it there per `AGENTS.md` and
`.devin/rules/` — same repo, same branch, same PR.

## 4. Branch and fix

    git switch master && git pull --ff-only
    git switch -c fix/sentry-<issue_short_id>

If the working tree has uncommitted changes that block the
switch, stop and ask the user before proceeding.

- Read `AGENTS.md` and `.devin/rules/*` first; 79-char lines in
  every file type.
- `export PATH="/opt/homebrew/bin:$PATH"` on every exec call —
  node/npm/gh are not on the default PATH.
- Write a failing test reproducing the event first, then fix.
- DANGER: `.env`'s `DATABASE_URL` is PRODUCTION with an admin
  user. Never run bare `test`/`migrate`/`sqlmigrate` — prefix
  `DATABASE_URL=sqlite:///db.sqlite3`. `makemigrations` is safe.
  Do not run scraper commands casually — they hit live sites and
  paid APIs; use `--dry-run`/`--limit`.
- Verify before committing:

      python manage.py check
      DATABASE_URL=sqlite:///db.sqlite3 \
        python manage.py test <app-you-changed>

  Frontend changes additionally (cwd `frontend/`):

      npm run typecheck && npm test

- Regenerate `frontend/openapi.json` + `src/*/api-types.ts` when
  the API shape changed (CI fails on drift).
- Update the relevant doc (`docs/` or the app's README) when
  behavior changed.

## 5. Draft PR

- Stage only files you edited, by path (never `git add -A` /
  `git add .`). Never commit plan/scratch markdown.
- Commit format `Type: Capitalized message` (usually `Fix:`).
- `git push -u origin <branch>`, then a DRAFT PR `--base master`
  per `.devin/workflows/create-pr.md` — write the body to a temp
  file and use `--body-file`, never inline `--body`.
- Body must: link the Sentry issue
  (`https://industry-analyser-ue.sentry.io/issues/<id>/`), quote
  the top stack frame, and include the UI verification / QC
  section.
- `gh pr checks <N> --watch`; the `frontend-checks` workflow runs
  typecheck, vitest, and the openapi/api-types drift check. Fix
  until green, then `gh pr ready`.

## 6. Resolve — only after merge

    curl -s -X PUT -H "$AUTH" \
      -H 'Content-Type: application/json' \
      -d '{"status": "resolvedInNextRelease"}' \
      "$BASE/issues/<id>/"

Release = deploy revision sha; resolution takes effect on the
next deploy. NEVER resolve before merge; NEVER `ignore` /
`archive` an issue without asking the user.

## Guardrails

- Leave Known-gaps items alone (`AGENTS.md`): don't touch
  `vercel.json`/`deploy-cloudrun.sh`, don't delete `accounts/`,
  don't "fix" `DEBUG=False` in `.env`.
- If >3 actionable items exist, post the queue list and let the
  user pick before fixing.
- Report at the end: issue handled, PR URL, and Sentry
  resolution status.

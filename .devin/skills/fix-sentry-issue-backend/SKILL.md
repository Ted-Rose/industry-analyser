---
name: fix-sentry-issue-backend
description: Pull unresolved production errors from the Sentry
  industry-analyser-api project, reproduce and fix them on a
  branch cut from main, open a PR, and mark the Sentry
  issue resolved only after the PR merges. Invoke when the user
  asks to fix Sentry issues / triage the Sentry queue in
  industry-analyser.
---

# Fix an unresolved Sentry issue (industry-analyser-api)

Target repo: this one — `Ted-Rose/industry-analyser` (remote
`origin`, the user's own repo, not a fork; default branch
`main`). The Sentry project is `industry-analyser-api` in org
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
    PROJECT="industry-analyser-api"

REST curl is unaffected by the machine's Netskope
TLS-intercepting proxy — the silent-failure quirk in `AGENTS.md`
applies only to the Python SDK's egress.

## 1. Fetch the work queue

    curl -s -H "$AUTH" \
      "$BASE/projects/$ORG/$PROJECT/issues/\
?query=is:unresolved+level:error+environment:production\
&statsPeriod=14d&sort=freq"

Only `level:error` events are auto-fixable — that filter IS
the queue: unhandled 500s (`DjangoIntegration`) and caught
bugs (`capture_internal_exception`, tag
`error_code:internal_error`). Warning-level
`error_code:rate_limited` / `provider_error` events
(`capture_provider_exception` — scraper/AI upstream outages)
are trend-only, NOT bugs to fix; surface them as a digest if
the user asks. Browser errors live in the sibling
`industry-analyser-web` project — see
`fix-sentry-issue-frontend`.

## 2. Pick and analyze one item

- Default: ONE item per run — the highest-count/recent issue.
  If the user said "fix all", enumerate first and post the
  list.
- Fetch `GET $BASE/issues/<id>/events/latest/` — exception
  type, stack frames, `error_code` tag (`internal_error` =
  caught bug vs untagged unhandled 500), request URL/view,
  release (`K_REVISION` sha), breadcrumbs.

## 3. Decide where the fix belongs

A Django exception can still be a contract problem caused by
the SPA — but both sides live in THIS repo, so fix wherever
the root cause is; same branch, same PR.

## 4. Branch and fix

    git switch main && git pull --ff-only
    git switch -c fix/sentry-<issue_short_id>

- Read `AGENTS.md`; 79-char lines in every file type.
- `source venv/bin/activate` before any `manage.py` command.
  The default `DATABASE_URL` is PRODUCTION — for read-only
  investigation use the `ai_agent` creds from
  `private_settings.json`; tests/scratch writes MUST use
  `DATABASE_URL=sqlite:///db.sqlite3`.
- Write a failing test reproducing the event first, then fix.
- Verify scoped, never the whole suite:
  `python manage.py check`,
  `DATABASE_URL=sqlite:///db.sqlite3
  python manage.py test <app>`.
- Regenerate `frontend/openapi.json` + `api-types.ts` when
  the API surface changed (CI drift-checks both).

## 5. Open the PR

- Stage only files you edited, by path (never `git add -A`);
  `git status` first and leave the user's dirty files alone.
- Commit format `Type: Capitalized message` (usually `Fix:`).
- `git push -u origin <branch>`, then a PR (ready for review,
  never a draft) `--base main` per the `/create-pr` skill —
  body via `--body-file`, never inline `--body`.
- Body must: link the Sentry issue
  (`https://industry-analyser-ue.sentry.io/issues/<id>/`),
  quote the top stack frame and request path, and include the
  UI verification / QC section.
- `gh pr checks <N> --watch`; fix until green. Then run the
  reviewer loop: spawn a fresh reviewer subagent on the diff,
  fix useful findings, push, repeat until a round finds
  nothing meaningful. Remove the worktree once the loop is
  clean and checks are green.

## 6. Resolve — only after merge

    curl -s -X PUT -H "$AUTH" \
      -H 'Content-Type: application/json' \
      -d '{"status": "resolvedInNextRelease"}' \
      "$BASE/issues/<id>/"

Release = deploy sha; resolution takes effect on the next
deploy. NEVER resolve before merge; NEVER `ignore` / `archive`
an issue without asking the user.

## Guardrails

- If >3 actionable items exist, post the queue list and let
  the user pick before fixing.
- If the fix needs a prod migration or data fix, stop and hand
  the command to the user — never run `migrate`,
  `terraform apply` or mutating `gcloud` yourself.
- No documented test login — the app uses Django session auth;
  `createsuperuser` for a local admin, and ask before
  inventing credentials.
- Report at the end: issue handled, PR URL, and Sentry
  resolution status.

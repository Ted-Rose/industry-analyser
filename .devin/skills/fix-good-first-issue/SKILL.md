---
name: fix-good-first-issue
description: Pick an open GitHub issue labeled "good first
  issue" in Ted-Rose/industry-analyser, fix it on a new branch
  cut from master, open a draft PR, wait for checks, fix any
  failures, and mark the PR ready for review. Invoke when the
  user asks to fix a good-first-issue / pick up an issue.
---

# Fix a "Good First Issue" in industry-analyser

Single repo — the GitHub repo is `Ted-Rose/industry-analyser`
(remote `origin`, the user's own repo, not a fork). Default
branch: `master`. Requires the `gh` CLI; if it is not installed,
tell the user to `brew install gh` rather than working around it.

## 1. Pick an issue

List candidates:

    gh issue list --repo Ted-Rose/industry-analyser \
      --label "good first issue" --state open

- If the user gave an issue number, use it; otherwise pick the
  top candidate.
- Always verify no PR already covers the issue — even when the
  user gave the number explicitly:

      gh pr list --repo Ted-Rose/industry-analyser \
        --state all --search "#<N> in:title,body"

  Skip the issue if a PR references it (`Closes #<N>`,
  `Fixes #<N>`) or a `fix/issue-<N>-*` PR already exists. If the
  user explicitly asked for an already-claimed issue, tell them
  which PR covers it and ask whether to proceed anyway.
- Read the chosen issue fully:

      gh issue view <N> --repo Ted-Rose/industry-analyser \
        --comments

If no unclaimed issues remain, stop and tell the user.

## 2. Decide which part of the stack the fix belongs in

One repo, two stacks: the Django backend (`fetcher/`,
`classified_ads/`, `blogs/`, `tv_programs/`, `scrape_jobs/`,
`ai_providers/`) and the React SPA (`frontend/src/<app>/`). The
shared contract is the django-ninja API surface —
`frontend/openapi.json` + generated `api-types.ts`. Symptoms
that look like API bugs but are client bugs (wrong params, not
handling an existing response field) belong in `frontend/`. If
the API shape changes, regenerate `openapi.json` and
`api-types.ts` (CI fails on drift). If unsure, state your
reasoning and ask the user before branching.

## 3. Branch from `master`

    git switch master
    git pull --ff-only
    git switch -c fix/issue-<N>-<short-slug>

If the working tree has uncommitted changes that block the
switch, stop and ask the user before proceeding.

## 4. Fix the issue

- Read `AGENTS.md` first — it is the source of truth for
  conventions (scraper contract, custom managers, DB guardrails,
  testing). `DOCUMENTATION_INDEX.md` is partly stale.
- Implement the fix; add or update tests.
- Keep every line <= 79 characters, in every file type.
- DANGER: `.env`'s `DATABASE_URL` is PRODUCTION with an admin
  user. Never run `migrate`/`sqlmigrate`/bare `test` without the
  `DATABASE_URL=sqlite:///db.sqlite3` prefix. `makemigrations`
  is safe. Do not run scraper commands casually — they hit live
  sites and paid APIs; use `--dry-run`/`--limit`.
- Leave Known-gaps items alone (see AGENTS.md): don't touch
  `vercel.json`/`deploy-cloudrun.sh`, don't delete `accounts/`,
  don't "fix" `DEBUG=False` in `.env`, keep `frontend_dist/`
  rebuilt when frontend sources change.
- Verify before committing:

      python manage.py check
      DATABASE_URL=sqlite:///db.sqlite3 \
        python manage.py test <app-you-changed>

  Frontend changes additionally:

      cd frontend && npm run typecheck && npm test

- If API behavior changed, update the relevant doc
  (`DOCUMENTATION_INDEX.md`, `docs/`, or the app's README).

## 5. Commit, push, and open a draft PR

- Stage only files you edited — never `git add -A` /
  `git add .`. Never commit plan/scratch markdown.
- Commit message format: `Type: Capitalized message`
  (e.g. `Fix: Return 404 for unknown book names`).
- Push:

      git push -u origin fix/issue-<N>-<short-slug>

- Create the PR as a DRAFT with `--base master`. Follow
  `.devin/workflows/create-pr.md`: write the body to a temp file
  and use `--body-file` (never inline `--body`):

      gh pr create --draft \
        --title "Type: Capitalized message" \
        --base master --head fix/issue-<N>-<short-slug> \
        --body-file pr-body.md
      rm pr-body.md

- The PR body must link the issue with `Closes #<N>` and include
  a UI verification / QC section: concrete steps (pages, clicks,
  expected result) exercising the change end-to-end. Omit only
  if genuinely unreachable from UI — then give an equivalent
  (curl command, log line).

## 6. Wait for checks; fix failures

    gh pr checks <PR-number> --watch

- The `frontend-checks` workflow runs typecheck, vitest, and an
  openapi.json/api-types.ts drift check on every PR.
- If any check fails, get details (`gh run view --log-failed`
  for logs), fix, commit, push, and watch again. Repeat until
  green. Do not mark ready while checks are pending or failing.

## 7. Mark ready for review and report

    gh pr ready <PR-number>

Then report to the user: the issue number/title fixed, the PR
URL, and the final check status.

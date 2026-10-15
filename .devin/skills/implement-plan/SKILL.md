---
name: implement-plan
description: Implement a plan markdown file end-to-end with
  subagents — run an implementation agent that cuts a feature
  branch and opens a draft PR, then review the PR with fresh
  reviewer agents and iterate fix rounds until reviewers
  report no issues. Invoke when the user asks to
  implement/execute a plan file (e.g.
  docs/plans/*-plan.md) using agents.
---

# Implement a Plan File with Subagents

Orchestrate a multi-agent implementation of a plan file in
`docs/plans/` (e.g. `docs/plans/property_linking_plan.md`).
Single repo: `Ted-Rose/industry-analyser`, default branch
`master`, remote `origin` (user's own repo, not a fork).

Subagents are stateless: front-load every prompt with the plan
path, the branch name, the conventions files to read, and
exactly what to return. Agents share the working tree — never
let two agents write files concurrently.

Track the phases with `todo_write`.

## Phase 0 — Read the plan

Read the plan file yourself. Extract: a short `<slug>` for the
branch name, which parts of the stack it touches (Django apps,
`frontend/`, `terraform/`, `docs/`), the contract between parts
(API shapes in `frontend/openapi.json`, model fields, command
args), and whether it needs a DB migration (write the migration
files — agents must NOT run `migrate` against the default
prod `DATABASE_URL`).

## Phase 1 — Implementation (one general agent)

Launch ONE `subagent_general` in the background. (Two agents
must never write the same repo concurrently — if the plan
splits into independent parts, run them SEQUENTIALLY, or split
the work yourself into one prompt per stage.) Prompt:

    Implement <plan-file> (absolute path) in the
    industry-analyser repo.

    1. git switch master && git pull --ff-only;
       git switch -c feat/<slug>
    2. Read AGENTS.md first (repo root). Every line <= 79
       chars in every file type.
       DANGER: .env's DATABASE_URL is PRODUCTION. Never run
       migrate/sqlmigrate/bare `test` without the
       DATABASE_URL=sqlite:///db.sqlite3 prefix.
       `makemigrations` is safe — if the plan needs a
       migration, generate the files and commit them; CI
       applies them on master.
    3. Implement the plan's contract exactly — other parts
       (API consumers, jobs) are written against it.
    4. Add/update tests per the plan. Verify:
         python manage.py check
         DATABASE_URL=sqlite:///db.sqlite3 \
           python manage.py test <changed-apps>
       Frontend changes additionally:
         cd frontend && npm run typecheck && npm test
       API-surface changes: regen openapi.json +
       npm run gen:types (CI drift check).
    5. Commit only files you edited (never git add -A, never
       commit plan/scratch md). Format: `Type: Capitalized
       msg`. Push: git push -u origin feat/<slug>
    6. Open a DRAFT PR with --base master following
       .devin/workflows/create-pr.md — write the body to
       pr-body.md, use --body-file, rm it after. Body must
       include a UI-verification section.
    7. gh pr checks <N> --watch; fix failures until green,
       then gh pr ready <N>.
    Return: PR URL, files changed, test results, anything you
    could not do (e.g. a migrate command for the user).

## Phase 2 — Review (fresh reviewer agent)

When the implementation PR exists, launch ONE NEW
`subagent_general` reviewer in the background. A new agent —
never reuse the implementer. Prompt:

    Review PR <url> in the industry-analyser repo. Do NOT
    modify any files — review only. The PR implements
    <plan-file> (absolute path); read the plan.
    1. gh pr diff <N> and read surrounding code for context.
    2. Check: correctness vs the plan, edge cases, contract
       match (API shapes vs openapi.json/api-types.ts,
       BaseScraper pipeline conventions, custom managers —
       `all_objects` where required), tests actually cover
       the change, 79-char limit, no plan/scratch files in
       the diff, no migration FILES missing when models
       changed, no prod-touching commands or secrets added.
    3. Optionally run the repo's scoped tests
       (DATABASE_URL=sqlite:///db.sqlite3 python manage.py
       test <app>).
    Return: numbered findings, each with severity
    (blocker|should-fix|nit) and file:line. Say "NO ISSUES"
    explicitly if clean.

## Phase 3 — Fix loop

If the reviewer reported blocker/should-fix findings:

1. Launch one `subagent_general` fixer (the PR branch is still
   checked out — verify with `git branch --show-current`, else
   switch to it). Prompt: the PR URL, the numbered findings
   verbatim, "fix, commit (`Fix: ...`), push, re-watch
   `gh pr checks`, return what changed". Nits may be batched
   into one fixer or skipped — say which.
2. After fixes land, launch a NEW reviewer agent (fresh round,
   same review prompt + "previous findings: <list> — verify
   the fixes").
3. Repeat until a review round reports NO ISSUES, or after 3
   rounds. If issues persist past 3 rounds, stop and report
   the remaining findings to the user.

## Guardrails

- Background agents cannot request new permissions. If one is
  blocked by a denied tool (e.g. `git push`, `gh`), resume it
  in the foreground so the user can approve.
- Never two agents writing the repo concurrently; fixers run
  one at a time.
- If a subagent reports the plan is unimplementable as
  written, stop and ask the user rather than improvising.

## Final report

PR URL, review rounds needed, findings fixed per round, and
any outstanding items (e.g. a `DATABASE_URL=... migrate`
command the user must run).

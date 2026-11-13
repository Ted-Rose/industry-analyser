---
name: openspec-apply-delegated
description: >
  Implement an OpenSpec change hands-off via subagents — an
  implementer agent cuts a feature branch, works the task list,
  and opens a PR ready for review; once checks are green a
  fresh reviewer agent reports severity-tagged findings and
  fixer agents
  iterate until clean. Use when asked to implement an OpenSpec
  change end-to-end without driving the task loop interactively.
---

# Apply an OpenSpec change via subagents

Orchestrator role — you coordinate; subagents implement, review,
and fix. The inner implementation follows the vendored
`openspec-apply-change` workflow inside a subagent, so this file
stays small and survives `openspec update`.

## Phase 1 — select and load the change

1. Resolve the change name from the argument or conversation
   context; if ambiguous, run `openspec list --json` and ask the
   user to pick. Announce: "Using change: <name>".
2. Run from the repo root (prefix shells with
   `export PATH="/opt/homebrew/bin:$PATH"`):

   ```bash
   openspec instructions apply --change "<name>" --json
   ```

   - `state: "blocked"` → do not delegate; show the user the
     message and missing artifacts, then stop.
   - `state: "all_done"` → nothing to implement; say so.
   - Otherwise collect the task file path, `contextFiles`, and
     task count — the implementer prompt needs them.
   - If a store is in play (`--store <id>`), pass the flag
     through to every openspec command here and inside the
     subagent prompt.

3. Branch: `feat/<change-name>` unless the user says otherwise.
   Never `main`.

## Phase 2 — implementer agent

4. Launch one background subagent (`subagent_general`,
   `is_background=true`). Subagents are stateless — the prompt
   must contain, verbatim or by path reference:
   - the change name, repo root path, and the `--store <id>`
     flag if one was selected
   - instruction to read
     `.devin/skills/openspec-apply-change/SKILL.md` and follow
     its steps 2-7 (status → apply instructions → context files
     → per-task implement loop → mark `- [x]` at each task's
     sourcePath/line → rerun instructions to confirm progress)
   - the repo rules that bite: max 79 chars/line (vendored
     `openspec-*/` files exempt), `Type: Capitalized` commits,
     feature branch only, never `manage.py migrate`, scoped
     tests only (`manage.py test <app>`, single Vitest file),
     and `openspec validate --all --strict` must pass before
     pushing
   - PR conventions: push the branch, body via temp file +
     `gh pr create --body-file`, ready-for-review PR (never a
     draft), mandatory UI verification section (follow
     `.devin/skills/create-pr/` when that skill exists in the
     repo).
   - archive timing: when EVERY tasks.md item is `- [x]`,
     run `openspec archive <name>` on the feature branch
     BEFORE pushing / opening the PR (check
     `openspec archive --help` first — it syncs delta specs
     into `openspec/specs/` and moves the change dir to
     `openspec/changes/archive/`); then `openspec validate
     --all --strict` must pass. The archive lands in the SAME
     commits pushed for the PR — code + synced specs +
     history together. A fully-implemented change must NOT
     reach PR completion unarchived; a legitimately
     unfinished task stays `- [ ]`, the change stays
     unarchived, and the implementer reports that
     explicitly.
   - report back: branch name, PR URL, tasks completed, any
     tasks it could not finish and why
5. If the implementer reports a blocker (unclear task, design
   issue, denied permission), do NOT let it improvise — surface
   the blocker to the user and pause the run.

## Phase 3 — wait for green

6. Watch checks before reviewing (`gh pr checks <n> --watch`,
   or poll). A failing check is a `[blocker]` finding — send
   the failing check log excerpt to the fixer in phase 4.

## Phase 4 — review / fix loop (max 3 rounds)

7. Launch a FRESH reviewer subagent (`subagent_explore`) that
   has never seen the implementation. Prompt it with:
   `gh pr diff <n>`, the change's contextFiles (proposal,
   specs, design, tasks paths), and the repo rules. It also
   verifies the archive is part of the PR: delta content
   synced into `openspec/specs/`, the change dir moved under
   `openspec/changes/archive/`, and `openspec validate
   --all --strict` passing — a fully-implemented change with
   no archive in the PR is a `[major]` finding, while
   unchecked tasks explain an absent archive. It returns
   findings tagged `[blocker]`, `[major]`, `[minor]`, `[nit]`,
   or the exact string `NO ISSUES`.
8. On `[blocker]` or `[major]` findings, launch a fixer
   subagent (`subagent_general`) on the SAME branch to commit
   and push fixes. Then start a new round with a NEW reviewer.
   Repeat until `NO ISSUES` (or only `[minor]`/`[nit]`) — max
   3 rounds, then stop and report what remains.
9. Never let the implementer or a fixer review its own work —
   every review round uses a fresh agent.

## Guardrails

- Only one agent writes to the branch at a time: implementer,
  then sequential fixers.
- Background subagents cannot gain permissions — if one stalls
  on a denied call, resume it in the foreground
  (`run_subagent resume=<agent_id>`).
- The PR is never a draft — a review round returning clean
  means it's done.
- Tasks that cannot be finished stay unchecked (`- [ ]`) — the
  fixer and reviewer must treat an unchecked task as incomplete
  work, not as a defect to review.
- Final report: PR URL, branch, tasks done/total, review
  rounds, unresolved findings, check status, and whether the
  archive was included in the PR or deferred (with the
  reason) — the archive now lands inside the implementing
  PR, not as a post-merge follow-up.

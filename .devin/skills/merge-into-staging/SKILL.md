---
name: merge-into-staging
description: >
  Roll open pull requests into the `staging` integration
  branch — sync staging with main first, retarget each
  open PR onto staging, then squash-merge so the user can
  pull `staging` locally and test everything together
  (local deployments double as the staging environment).
  Use when asked to stage PRs, update staging, or prepare
  a local testing branch.
argument-hint: "[pr-number ...]"
allowed-tools:
  - exec
---

# Merge open PRs into staging

`staging` is a long-lived integration branch: work lands
there first, the user pulls it locally to test (local
deployments ARE the staging environments), and it reaches
`main` only when the user asks for a release. Nothing in
this skill commits to `main`.

Unless PR numbers are given as arguments, process ALL
open, non-draft PRs, oldest first.

1. `export PATH="/opt/homebrew/bin:$PATH"` — gh/git are
   Homebrew installs and not on the default PATH.
2. `REPO=$(gh repo view --json nameWithOwner \
   -q .nameWithOwner)` and `git fetch origin`. Pass
   `--repo "$REPO"` to every `gh` call.
3. Ensure the branch exists:
   `git ls-remote --heads origin staging` — if empty,
   `git push origin origin/main:refs/heads/staging`.
4. Sync `main` into `staging` so it never falls behind:
   `gh api -X POST "repos/$REPO/merges" -f base=staging \
   -f head=main` — 201 = merged, 204 = already up to
   date, 409 = conflict. On conflict:
   `git worktree add ../$(basename "$PWD")-wt/stage-sync \
   -b stage-sync origin/staging`, then
   `git -C <path> merge origin/main`, resolve keeping BOTH
   sides' intent (intentional deletions on main — e.g.
   retired workflows — stay deleted), commit the merge,
   `git -C <path> push origin HEAD:staging`, then
   `git worktree remove --force <path>`.
5. List targets:
   `gh pr list --repo "$REPO" --state open --json \
   number,title,headRefName,baseRefName,isDraft`.
   Skip drafts and any PR whose head is `main`/`staging`.
6. For each PR: retarget when its base is not staging —
   `gh pr edit <n> --base staging` — poll
   `gh pr view <n> --json mergeable -q .mergeable` until
   MERGEABLE, then `gh pr merge <n> --squash
   --delete-branch`. If GitHub reports CONFLICTING, land
   it manually in the stage-sync worktree instead:
   `git merge --squash origin/<headRefName>`, resolve,
   `git commit -m "<pr title> (#<n>)"`,
   `git push origin HEAD:staging`, then `gh pr close <n>`
   with a comment that it was merged into staging
   manually.
7. Report: per-PR merged/skipped/failed, the new staging
   tip, and remind the user local testing is
   `git checkout staging && git pull` — the local
   deployment is the staging environment, so verify there
   before anything is promoted to `main`.

Never commit on `main`, never force-push `staging`, and
never merge a PR whose own checks conclude FAILED —
report it and move on.

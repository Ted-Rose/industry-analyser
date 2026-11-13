---
name: create-pr
description: >
  Open a pull request for the current feature branch the
  repo-approved way — body via a temp file and
  `gh pr create --body-file`, mandatory UI verification section,
  draft first. Use when asked to create/open a PR or push changes
  for review.
---

# Create a PR

1. Prereqs: on a feature branch (never `main` — if on `main`,
   `git checkout -b` first and move the commits). `gh` installed
   and authed; if missing, tell the user
   `brew install gh && gh auth login`. All `gh` calls target
   `Ted-Rose/industry-analyser` (remote `origin`).
2. `git status` — stage only this session's files, by path. Never
   `git add -A` / `git add .` / `git commit -a`; leave the user's
   dirty files and untracked secrets (`.env`,
   `private_settings.json`, `ca.pem`, …) alone.
3. Commit with `Type: Capitalized message` (Feat/Fix/Docs/
   Refactor/Test/Chore). Check nothing over 79 chars was
   committed:
   `awk 'length > 79 {print FILENAME":"NR}' <changed files>`.
4. `git push -u origin <branch>`.
5. Write the PR body to a temp file at the repo root
   (`pr-body.md`), then `gh pr create --draft --title "Feat: …"
   --body-file pr-body.md`. NEVER pass the body inline via
   `--body`. Delete the temp file afterwards.
6. Body template:

   ```markdown
   ## Summary
   <what + why, 2-4 bullets>

   ## UI verification / QC
   1. `./dev.sh`, open http://localhost:8274/…
   2. <click X, submit Y>
   3. Expected: <observable result>

   ## Test plan
   - [ ] `python manage.py check`
   - [ ] `DATABASE_URL=sqlite:///db.sqlite3
         python manage.py test <app>`
   - [ ] `npm run typecheck && npm test` (when frontend/
         changed)
   ```

   The UI verification section is mandatory — concrete pages,
   clicks and expected results that exercise the change
   end-to-end (UI drives the backend too). Omit it ONLY when
   genuinely unreachable from the UI, and then document an
   equivalent (curl command, `dbshell` query, log line to
   watch) under the same heading.
7. `gh pr checks --watch` until green (frontend-checks.yml).
   Fix failures on the branch, push again.
8. `gh pr ready` when the user asked for a reviewable PR; leave
   it draft otherwise. Report the PR URL.

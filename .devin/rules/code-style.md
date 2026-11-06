---
description: "Python/Django code style for this repo"
trigger: always_on
---

- Max line length: **79 characters** (enforced by `.flake8`).
  Exemption: vendored OpenSpec skill files —
  `.agents/skills/openspec-*/` and their `.devin/skills/`
  copies — carry upstream >79-char prose.
- Use `logging.getLogger('<app_name>')` — e.g.
  `logging.getLogger('fetcher')` — not `__name__`. App-named
  loggers are pre-configured in `industry_analyser/settings.py`
  with rotating file handlers.
- Django style: function-based views, app-level `urls.py` with
  `app_name`, explicit `db_table`/`unique_together` on models.
- Dependencies live in TWO places that MUST stay in sync:
  `requirements.txt` (canonical — local venv, Dockerfile/Cloud
  Run) and `pyproject.toml` `dependencies` + `uv.lock` (what
  the Vercel serverless deploy installs). A requirements-only
  addition 500s every Vercel route — the root urlconf imports
  app urlconfs eagerly. Pin new deps in both files, then
  regenerate the lockfile with `uv lock`.
- Verify changes with `python manage.py check`; run tests only for the
  app you touched (`python manage.py test <app>`).

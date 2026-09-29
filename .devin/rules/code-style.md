---
description: "Python/Django code style for this repo"
trigger: always_on
---

- Max line length: **79 characters** (enforced by `.flake8`).
- Use `logging.getLogger('<app_name>')` — e.g. `logging.getLogger('fetcher')` —
  not `__name__`. App-named loggers are pre-configured in
  `industry_analyser/settings.py` with rotating file handlers.
- Django style: function-based views, app-level `urls.py` with
  `app_name`, explicit `db_table`/`unique_together` on models.
- `requirements.txt` is the canonical dependency list (not
  `pyproject.toml`); pin new deps.
- Verify changes with `python manage.py check`; run tests only for the
  app you touched (`python manage.py test <app>`).

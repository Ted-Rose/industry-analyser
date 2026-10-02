---
description: "Local migrations allowed; prod migrated by CI"
trigger: always_on
---

Migrations are fully allowed **locally**: the dev database is the
gitignored SQLite file `db.sqlite3`, so run `python manage.py
makemigrations` and `python manage.py migrate` freely — generate
migration files after every model change and apply them to verify,
no need to ask the user.

Do **not** run migrations against the production database. Production
migrations are applied by `.github/workflows/run-migrations.yml`: after
the deploy workflow completes on `master` it detects changed
`migrations/` files and executes a `run-migrations` Cloud Run job
(`python manage.py migrate`). Ship migration files in the commit;
CI applies them.

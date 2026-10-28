---
description: "Local migrations allowed; prod migrated manually"
trigger: always_on
---

Generate migration files freely — `python manage.py makemigrations`
touches no database. But **the local `.env` `DATABASE_URL` points at
the production Aiven PostgreSQL by default**, so apply migrations
only against SQLite:

```bash
DATABASE_URL=sqlite:///db.sqlite3 python manage.py migrate
```

Same override for tests — the test runner creates a database on
whatever `DATABASE_URL` targets.

Do **not** run migrations against the production database casually.
There is no CI migration step — the `run-migrations` Cloud Run job
and `.github/workflows/run-migrations.yml` were removed. Ship
migration files in the commit, then the maintainer applies them to
prod **manually**: `python manage.py migrate` with the prod
`DATABASE_URL` (the `.env` default), or via a one-off job in the
GCP console.

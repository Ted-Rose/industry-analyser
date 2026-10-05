---
description: "Local migrations allowed; prod migrated by CI"
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

Do **not** run migrations against the production database. Production
migrations are applied by `.github/workflows/run-migrations.yml`: after
the deploy workflow completes on `master` it detects changed
`migrations/` files and executes a `run-migrations` Cloud Run job
(`python manage.py migrate`). Ship migration files in the commit;
CI applies them.

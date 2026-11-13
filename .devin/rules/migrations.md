---
description: "Local migrations allowed; prod migrated by CI deploy"
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
Prod migrations are applied **by CI**: the `build-and-deploy` job in
`.github/workflows/deploy-web-service.yml` deploys a `run-migrations`
Cloud Run job from the just-built image and executes it before the
new service revision goes live — a failed `migrate` aborts the
deploy. Just ship migration files in the commit. Manual
`python manage.py migrate` against prod is reserved for recovery.

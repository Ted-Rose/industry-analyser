---
description: "Never run database migrations"
trigger: always_on
---

Never run database migrations. Do not run `python manage.py migrate`,
`python manage.py makemigrations`, or any equivalent migration command
against any environment. If a migration is required, ask the user to run
it themselves.

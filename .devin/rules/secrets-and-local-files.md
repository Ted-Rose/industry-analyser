---
description: "Secrets and gitignored local state — never commit or print"
trigger: always_on
---

Never commit, print, or copy into code/docs the contents of these
gitignored local files:

- `.env`, `ca.pem`, `private_settings.json` — secrets/certs
- `db.sqlite3`, `db_backups/` — local database state
- `fetcher/config_v2.json`, `blogs/config.yaml` — local scraper config
- `terraform/terraform.tfvars`, `terraform/tfplan`, `*.tfstate`

Production secrets live in GCP Secret Manager and GitHub Actions
secrets (`GCP_SA_KEY`, `TF_VAR_*`). If a task needs a secret value, ask
the user — don't search the filesystem or repo history for it.

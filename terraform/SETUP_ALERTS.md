# Quick Setup Guide: Email Alerts for Cloud Run Job Failures

## What This Does

Automatically sends you an email whenever the `all-jobs` Cloud Run
job fails (it runs every enabled sub-job from the `run_all_jobs`
JOBS list and exits non-zero when any of them fails). A second
log-based policy mails on individual `SCRAPE_ITEM_FAILED` markers.

## Setup (3 minutes)

### 1. Add `ALERT_EMAIL` to the `env-file` secret

The alert email lives inside the consolidated `env-file` secret
(the same `.env` payload Cloud Run injects as `DOTENV`) —
`monitoring.tf` parses `ALERT_EMAIL` out of it at plan time.

Append the line to the current payload and push a new version:

```bash
gcloud secrets versions access latest --secret=env-file \
  --project=gen-lang-client-0833674612 > /tmp/env-file.txt
printf '\nALERT_EMAIL=YOUR_EMAIL_HERE\n' >> /tmp/env-file.txt
gcloud secrets versions add env-file \
  --project=gen-lang-client-0833674612 \
  --data-file=/tmp/env-file.txt
```

**Replace `YOUR_EMAIL_HERE` with your actual email address.**

Do **not** upload your local `.env` wholesale — the prod
`env-file` payload has drifted from it (different keys/values).
Patch the downloaded payload only, as above.

### 2. Apply the Terraform changes

```bash
cd terraform
terraform init  # Only needed if first time
terraform plan  # Review what will be created
terraform apply # Type 'yes' to confirm
```

### 3. Verify it worked

```bash
terraform output notification_channel_email
terraform output alert_policies
```

You should see the notification channel name and 2 alert policy names.

To verify the email (without exposing it in terraform output):

```bash
gcloud secrets versions access latest \
  --secret=env-file \
  --project=gen-lang-client-0833674612 | grep '^ALERT_EMAIL='
```

## What Gets Created

- **1 Email notification channel** - Reads your email from Secret Manager
- **2 Alert policies** - `all-jobs` execution failures + per-item
  SCRAPE_ITEM_FAILED log alerts
- **Monitoring API enabled** - If not already enabled

## Security Benefits

✅ **Email not in git** - Secret Manager keeps it secure  
✅ **Email not in terraform.tfvars** - No accidental commits  
✅ **Encrypted at rest** - Google manages encryption  
✅ **Access controlled** - Only authorized services can read it  

## Cost

**FREE** for typical usage (under 150 MB metrics/month)

Secret Manager: First 6 secret versions free, then $0.06/version/month

## Testing

To test that alerts work (optional):

1. Go to [Cloud Monitoring Console](https://console.cloud.google.com/monitoring/alerting/policies)
2. Find one of your alert policies
3. Click "Test" to send a test notification

Or manually trigger a job failure:
```bash
gcloud run jobs execute all-jobs --region=europe-north1
# (if it fails, you'll get an email)
```

## Updating Your Email

To change the email address, edit the `ALERT_EMAIL=` line inside
the `env-file` payload and push a new version:

```bash
gcloud secrets versions access latest --secret=env-file \
  --project=gen-lang-client-0833674612 > /tmp/env-file.txt
# edit /tmp/env-file.txt: change the ALERT_EMAIL= line
gcloud secrets versions add env-file \
  --project=gen-lang-client-0833674612 \
  --data-file=/tmp/env-file.txt

# Re-apply Terraform to update the notification channel
cd terraform
terraform apply
```

## Disabling Alerts

To turn off alerts, empty or remove the `ALERT_EMAIL=` line in
the `env-file` payload, push a new secret version (same commands
as "Updating Your Email" above), then:

```bash
cd terraform
terraform apply
```

An empty `ALERT_EMAIL` destroys all monitoring resources.

## Need Help?

See the full documentation: [MONITORING.md](./MONITORING.md)

## Troubleshooting

**Error: Secret not found / access denied on `env-file`**
```
Error: Error retrieving available secret manager secret version
```

Solution: the `env-file` secret must exist and the identity
running terraform (locally: your user; in CI: the deployer SA,
granted by the `deployer_env_file_accessor` resource) needs
`roles/secretmanager.secretAccessor` on it.

**Not receiving emails?**
1. Check your spam folder
2. Verify email in secret:
   ```bash
   gcloud secrets versions access latest --secret=env-file \
     | grep '^ALERT_EMAIL='
   ```
3. Check GCP Console: https://console.cloud.google.com/monitoring/alerting/notifications

**Want to change notification frequency?**
Edit `monitoring.tf` and change `period = "300s"` to your desired interval.

## View Secret in GCP Console

https://console.cloud.google.com/security/secret-manager/secret/env-file?project=gen-lang-client-0833674612

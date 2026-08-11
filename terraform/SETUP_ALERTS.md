# Quick Setup Guide: Email Alerts for Cloud Run Job Failures

## What This Does

Automatically sends you an email whenever any of your Cloud Run jobs fail:
- `scrape-vacancy`
- `scrape-tv-programs`
- `scrape-apartment-ads`
- `scrape-housing-ads`
- `sync-regions`

## Setup (3 minutes)

### 1. Create a Secret Manager secret with your email

Your email address will be stored securely in Google Secret Manager (not in terraform.tfvars or git).

Run this command and I'll provide you with the value to paste:

```bash
# Create the secret (you'll paste your email when prompted)
echo "YOUR_EMAIL_HERE" | gcloud secrets create industry-analyser-alert-email \
  --project=gen-lang-client-0833674612 \
  --replication-policy="automatic" \
  --data-file=-
```

**Replace `YOUR_EMAIL_HERE` with your actual email address.**

Or create it interactively:

```bash
gcloud secrets create industry-analyser-alert-email \
  --project=gen-lang-client-0833674612 \
  --replication-policy="automatic" \
  --data-file=-
# Then paste your email and press Ctrl+D (or Cmd+D on Mac)
```

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

You should see the notification channel name and 5 alert policy names.

To verify the email (without exposing it in terraform output):

```bash
gcloud secrets versions access latest \
  --secret=industry-analyser-alert-email \
  --project=gen-lang-client-0833674612
```

## What Gets Created

- **1 Email notification channel** - Reads your email from Secret Manager
- **5 Alert policies** - One for each Cloud Run job
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
gcloud run jobs execute scrape-vacancy --region=europe-north1
# (if it fails, you'll get an email)
```

## Updating Your Email

To change the email address:

```bash
# Create a new version of the secret
echo "new-email@example.com" | gcloud secrets versions add industry-analyser-alert-email \
  --project=gen-lang-client-0833674612 \
  --data-file=-

# Re-apply Terraform to update the notification channel
cd terraform
terraform apply
```

## Disabling Alerts

To turn off alerts, delete the secret:

```bash
gcloud secrets delete industry-analyser-alert-email \
  --project=gen-lang-client-0833674612

# Then apply to remove monitoring resources
cd terraform
terraform apply
```

Or just delete the secret version:

```bash
gcloud secrets versions destroy latest \
  --secret=industry-analyser-alert-email \
  --project=gen-lang-client-0833674612
```

## Need Help?

See the full documentation: [MONITORING.md](./MONITORING.md)

## Troubleshooting

**Error: Secret not found**
```
Error: Error retrieving available secret manager secret version
```

Solution: Create the secret first (see step 1 above)

**Not receiving emails?**
1. Check your spam folder
2. Verify email in secret:
   ```bash
   gcloud secrets versions access latest --secret=industry-analyser-alert-email
   ```
3. Check GCP Console: https://console.cloud.google.com/monitoring/alerting/notifications

**Want to change notification frequency?**
Edit `monitoring.tf` and change `period = "300s"` to your desired interval.

## View Secret in GCP Console

https://console.cloud.google.com/security/secret-manager/secret/industry-analyser-alert-email?project=gen-lang-client-0833674612

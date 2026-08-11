# Cloud Run Job Monitoring Setup

This document explains the Cloud Monitoring alert setup for Cloud Run job failures.

## Overview

The monitoring setup includes:
- **Email notification channel** - Sends alerts to your specified email address
- **Alert policies** - One for each Cloud Run job (scrape-vacancy, scrape-tv-programs, scrape-apartment-ads, scrape-blogs)
- **Comprehensive failure detection** - Catches ALL failure types including:
  - Application errors (non-zero exit codes)
  - OOM (Out of Memory) kills
  - Container startup failures
  - Timeout failures

## Configuration

### 1. Store your email in Secret Manager

Your email address is stored securely in Google Secret Manager (not in terraform.tfvars or git):

```bash
# Create the secret with your email
echo "your-email@example.com" | gcloud secrets create industry-analyser-alert-email \
  --project=gen-lang-client-0833674612 \
  --replication-policy="automatic" \
  --data-file=-
```

**Security Benefits:**
- ✅ Email not stored in git
- ✅ Encrypted at rest by Google
- ✅ Access controlled via IAM

**Note:** If the secret doesn't exist or is empty, no monitoring resources will be created.

### 2. Apply the Terraform configuration

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

### 3. Verify the setup

After applying, check the outputs:

```bash
terraform output notification_channel_email
terraform output alert_policies
```

You can also verify in the GCP Console:
- **Notification Channels**: https://console.cloud.google.com/monitoring/alerting/notifications
- **Alert Policies**: https://console.cloud.google.com/monitoring/alerting/policies

## How It Works

### Metric Monitored

The alerts monitor the `run.googleapis.com/job/completed_execution_count` metric with:
- `result="failed"` label
- Specific job name and region filters

### Alert Behavior

- **Trigger**: Any failed job execution (threshold > 0)
- **Notification rate limit**: Maximum one notification every 5 minutes per job
- **Auto-close**: Incidents auto-close after 24 hours
- **Documentation**: Each alert includes a direct link to the job's Cloud Run logs

### Email Notifications

When a job fails, you'll receive an email with:
- Job name and failure time
- Link to Cloud Run console for logs
- Details about what types of failures are detected

## Testing the Alerts

To test that alerts are working:

1. **Manually trigger a job to fail** (optional - for testing only):
   ```bash
   # Update a job to use a command that will fail
   gcloud run jobs update scrape-vacancy \
     --region=europe-north1 \
     --command="sh,-c,exit 1"
   
   # Execute the job
   gcloud run jobs execute scrape-vacancy --region=europe-north1
   
   # Restore the original command after testing
   terraform apply
   ```

2. **Check for the alert email** - Should arrive within a few minutes

3. **Verify in GCP Console**:
   - Go to [Cloud Monitoring Alerting](https://console.cloud.google.com/monitoring/alerting/incidents)
   - You should see an incident for the failed job

## Monitoring Costs

Cloud Monitoring pricing (as of 2024):
- **Notification channels**: Free
- **Alert policies**: Free
- **Metric ingestion**: First 150 MB/month free, then $0.258/MB
- **API calls**: First 1M calls/month free

For this setup with 4 jobs, the cost should be **minimal to free** under normal usage.

## Customization

### Change notification frequency

Edit the `notification_rate_limit` in `monitoring.tf`:

```hcl
alert_strategy {
  notification_rate_limit {
    period = "300s"  # Change to 600s for 10 minutes, etc.
  }
}
```

### Add additional notification channels

You can add Slack, PagerDuty, SMS, or other channels:

```hcl
# Example: Add Slack notification
resource "google_monitoring_notification_channel" "slack" {
  display_name = "Slack Alerts"
  type         = "slack"
  labels = {
    channel_name = "#alerts"
    url          = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
  }
}

# Then add to alert policy notification_channels
notification_channels = [
  google_monitoring_notification_channel.email[0].id,
  google_monitoring_notification_channel.slack.id,
]
```

### Monitor job duration or other metrics

You can create additional alerts for:
- Job execution time exceeding a threshold
- Job not running for X hours (missed schedule)
- Resource usage (CPU, memory)

Example for long-running jobs:

```hcl
resource "google_monitoring_alert_policy" "job_duration" {
  display_name = "Job taking too long"
  
  conditions {
    display_name = "Execution time > 2 hours"
    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_job\"",
        "metric.type=\"run.googleapis.com/job/execution_time\"",
      ])
      duration        = "0s"
      comparison      = "COMPARISON_GT"
      threshold_value = 7200  # 2 hours in seconds
    }
  }
}
```

## Troubleshooting

### Not receiving emails?

1. **Check spam folder** - GCP alerts sometimes go to spam
2. **Verify email address** - Check `terraform output notification_channel_email`
3. **Check notification channel status**:
   ```bash
   gcloud alpha monitoring channels list
   ```
4. **Verify alert policy is enabled**:
   ```bash
   gcloud alpha monitoring policies list
   ```

### False positives?

If you're getting alerts for expected failures (e.g., during testing):
- Temporarily disable the alert policy in the GCP Console
- Or remove the `alert_email` from `terraform.tfvars` and re-apply

### Want to disable monitoring?

Delete the secret:

```bash
gcloud secrets delete industry-analyser-alert-email --project=gen-lang-client-0833674612
terraform apply
```

This will destroy all monitoring resources.

### Want to update your email?

Add a new version to the secret:

```bash
echo "new-email@example.com" | gcloud secrets versions add industry-analyser-alert-email \
  --project=gen-lang-client-0833674612 \
  --data-file=-

terraform apply
```

## Additional Resources

- [Cloud Monitoring Documentation](https://cloud.google.com/monitoring/docs)
- [Alert Policy Reference](https://cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.alertPolicies)
- [Notification Channels](https://cloud.google.com/monitoring/support/notification-options)
- [Cloud Run Metrics](https://cloud.google.com/run/docs/monitoring)

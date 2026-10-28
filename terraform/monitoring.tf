# Data source to read alert email from Secret Manager
data "google_secret_manager_secret_version" "alert_email" {
  secret  = "industry-analyser-alert-email"
  project = var.project_id
}

# Email notification channel for Cloud Run job failures
resource "google_monitoring_notification_channel" "email" {
  count = data.google_secret_manager_secret_version.alert_email.secret_data != "" ? 1 : 0

  display_name = "Cloud Run Job Failure Alerts"
  type         = "email"
  labels = {
    email_address = trimspace(data.google_secret_manager_secret_version.alert_email.secret_data)
  }

  depends_on = [google_project_service.apis]
}

# Alert policy for the all-jobs master job. The former per-task job
# failure alerts were consolidated into this single policy: all-jobs
# runs `python manage.py run_all_jobs` and exits non-zero when any
# enabled sub-job fails, so one policy covers all scheduled work.
# Per-item failures inside a scrape still alert via the
# SCRAPE_ITEM_FAILED log-based policy below.
resource "google_monitoring_alert_policy" "all_jobs_failure" {
  count = data.google_secret_manager_secret_version.alert_email.secret_data != "" ? 1 : 0

  display_name = "Cloud Run Job Failure: all-jobs"
  combiner     = "OR"

  documentation {
    content   = <<-EOT
      The Cloud Run job "all-jobs" has failed.

      all-jobs runs `python manage.py run_all_jobs`, executing each
      enabled sub-job in scrape_jobs/management/commands/run_all_jobs.py
      sequentially; it exits non-zero when any sub-job fails.

      This alert monitors the completed_execution_count metric with
      result="failed" label.
      It catches all types of failures including:
      - Application errors
      - OOM (Out of Memory) kills
      - Container startup failures
      - Timeout failures

      Check the Cloud Run logs for details:
      https://console.cloud.google.com/run/jobs/details/${var.region}/all-jobs?project=${var.project_id}
    EOT
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Job execution failed"
    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_job\"",
        "resource.labels.job_name=\"all-jobs\"",
        "resource.labels.location=\"${var.region}\"",
        "metric.type=\"run.googleapis.com/job/completed_execution_count\"",
        "metric.labels.result=\"failed\""
      ])
      duration        = "0s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email[0].id
  ]

  alert_strategy {
    auto_close = "86400s"
  }

  depends_on = [
    google_cloud_run_v2_job.all_jobs,
    google_project_service.apis
  ]
}

# Log-based alert policies (condition_matched_log) make Monitoring
# create a logging notification rule, which requires
# logging.notificationRules.create — not covered by the deployer
# SA's monitoring.editor. The deployer SA is created outside
# terraform (GCP_SA_KEY secret); grant it logging.admin here so the
# policy below can be applied by CI (the SA holds
# resourcemanager.projectIamAdmin, so it can self-grant).
resource "google_project_iam_member" "deployer_logging_admin" {
  project = var.project_id
  role    = "roles/logging.admin"
  member  = "serviceAccount:industry-analyser-deployer@${var.project_id}.iam.gserviceaccount.com"
}

# Alert policy for individual scrape-item failures
# (stateful_scrape_jobs_plan.md section 5.4). ScrapeJobRunner logs a
# SCRAPE_ITEM_FAILED marker at ERROR for each failed item; this
# log-based policy mails on it via the existing email channel while
# the run itself continues (run ends PARTIAL, not FAILED).
resource "google_monitoring_alert_policy" "scrape_item_failure" {
  count = length(google_monitoring_notification_channel.email) > 0 ? 1 : 0

  display_name = "Scrape job item failure"
  combiner     = "OR"

  documentation {
    content   = <<-EOT
      A scrape-job work item failed inside a Cloud Run job execution.

      ScrapeJobRunner logs "SCRAPE_ITEM_FAILED job=<slug>
      item=<key> err=<error>" at ERROR; the run continues with the
      next item and finishes PARTIAL. Check the run's
      ScrapeJobRunItem rows in Django admin for details.
    EOT
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "SCRAPE_ITEM_FAILED log entry"
    condition_matched_log {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_job\"",
        "severity>=ERROR",
        "textPayload:\"SCRAPE_ITEM_FAILED\""
      ])
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email[0].id
  ]

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "86400s"
  }

  depends_on = [
    google_project_service.apis,
    google_project_iam_member.deployer_logging_admin,
  ]
}

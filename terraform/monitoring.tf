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

# DISABLED: Uncomment to re-enable
# # Alert policy for scrape-vacancy job failures
# resource "google_monitoring_alert_policy" "scrape_vacancy_failure" {
#   count = data.google_secret_manager_secret_version.alert_email.secret_data != "" ? 1 : 0
#
#   display_name = "Cloud Run Job Failure: scrape-vacancy"
#   combiner     = "OR"
#
#   documentation {
#     content   = <<-EOT
#       The Cloud Run job "scrape-vacancy" has failed.
#       
#       This alert monitors the completed_execution_count metric with 
#       result="failed" label.
#       It catches all types of failures including:
#       - Application errors
#       - OOM (Out of Memory) kills
#       - Container startup failures
#       - Timeout failures
#       
#       Check the Cloud Run logs for details:
#       https://console.cloud.google.com/run/jobs/details/${var.region}/scrape-vacancy?project=${var.project_id}
#     EOT
#     mime_type = "text/markdown"
#   }
#
#   conditions {
#     display_name = "Job execution failed"
#     condition_threshold {
#       filter = join(" AND ", [
#         "resource.type=\"cloud_run_job\"",
#         "resource.labels.job_name=\"scrape-vacancy\"",
#         "resource.labels.location=\"${var.region}\"",
#         "metric.type=\"run.googleapis.com/job/completed_execution_count\"",
#         "metric.labels.result=\"failed\""
#       ])
#       duration        = "0s"
#       comparison      = "COMPARISON_GT"
#       threshold_value = 0
#
#       aggregations {
#         alignment_period   = "60s"
#         per_series_aligner = "ALIGN_RATE"
#       }
#     }
#   }
#
#   notification_channels = [
#     google_monitoring_notification_channel.email[0].id
#   ]
#
#   alert_strategy {
#     auto_close = "86400s"
#   }
#
#   depends_on = [
#     google_cloud_run_v2_job.scrape_vacancy,
#     google_project_service.apis
#   ]
# }

# DISABLED: Uncomment to re-enable
# # Alert policy for scrape-tv-programs job failures
# resource "google_monitoring_alert_policy" "scrape_tv_programs_failure" {
#   count = data.google_secret_manager_secret_version.alert_email.secret_data != "" ? 1 : 0
#
#   display_name = "Cloud Run Job Failure: scrape-tv-programs"
#   combiner     = "OR"
#
#   documentation {
#     content   = <<-EOT
#       The Cloud Run job "scrape-tv-programs" has failed.
#       
#       This alert monitors the completed_execution_count metric with 
#       result="failed" label.
#       It catches all types of failures including:
#       - Application errors
#       - OOM (Out of Memory) kills
#       - Container startup failures
#       - Timeout failures
#       
#       Check the Cloud Run logs for details:
#       https://console.cloud.google.com/run/jobs/details/${var.region}/scrape-tv-programs?project=${var.project_id}
#     EOT
#     mime_type = "text/markdown"
#   }
#
#   conditions {
#     display_name = "Job execution failed"
#     condition_threshold {
#       filter = join(" AND ", [
#         "resource.type=\"cloud_run_job\"",
#         "resource.labels.job_name=\"scrape-tv-programs\"",
#         "resource.labels.location=\"${var.region}\"",
#         "metric.type=\"run.googleapis.com/job/completed_execution_count\"",
#         "metric.labels.result=\"failed\""
#       ])
#       duration        = "0s"
#       comparison      = "COMPARISON_GT"
#       threshold_value = 0
#
#       aggregations {
#         alignment_period   = "60s"
#         per_series_aligner = "ALIGN_RATE"
#       }
#     }
#   }
#
#   notification_channels = [
#     google_monitoring_notification_channel.email[0].id
#   ]
#
#   alert_strategy {
#     auto_close = "86400s"
#   }
#
#   depends_on = [
#     google_cloud_run_v2_job.scrape_tv_programs,
#     google_project_service.apis
#   ]
# }

# DISABLED: Uncomment to re-enable
# # Alert policy for scrape-apartment-ads job failures
# resource "google_monitoring_alert_policy" "scrape_apartment_ads_failure" {
#   count = data.google_secret_manager_secret_version.alert_email.secret_data != "" ? 1 : 0
#
#   display_name = "Cloud Run Job Failure: scrape-apartment-ads"
#   combiner     = "OR"
#
#   documentation {
#     content   = <<-EOT
#       The Cloud Run job "scrape-apartment-ads" has failed.
#       
#       This alert monitors the completed_execution_count metric with 
#       result="failed" label.
#       It catches all types of failures including:
#       - Application errors
#       - OOM (Out of Memory) kills
#       - Container startup failures
#       - Timeout failures
#       
#       Note: This job has max_retries=2, so it will retry twice before 
#       being marked as failed.
#       
#       Check the Cloud Run logs for details:
#       https://console.cloud.google.com/run/jobs/details/${var.region}/scrape-apartment-ads?project=${var.project_id}
#     EOT
#     mime_type = "text/markdown"
#   }
#
#   conditions {
#     display_name = "Job execution failed"
#     condition_threshold {
#       filter = join(" AND ", [
#         "resource.type=\"cloud_run_job\"",
#         "resource.labels.job_name=\"scrape-apartment-ads\"",
#         "resource.labels.location=\"${var.region}\"",
#         "metric.type=\"run.googleapis.com/job/completed_execution_count\"",
#         "metric.labels.result=\"failed\""
#       ])
#       duration        = "0s"
#       comparison      = "COMPARISON_GT"
#       threshold_value = 0
#
#       aggregations {
#         alignment_period   = "60s"
#         per_series_aligner = "ALIGN_RATE"
#       }
#     }
#   }
#
#   notification_channels = [
#     google_monitoring_notification_channel.email[0].id
#   ]
#
#   alert_strategy {
#     auto_close = "86400s"
#   }
#
#   depends_on = [
#     google_cloud_run_v2_job.scrape_apartment_ads,
#     google_project_service.apis
#   ]
# }

# DISABLED: Uncomment to re-enable
# # Alert policy for scrape-housing-ads job failures
# resource "google_monitoring_alert_policy" "scrape_housing_ads_failure" {
#   count = data.google_secret_manager_secret_version.alert_email.secret_data != "" ? 1 : 0
#
#   display_name = "Cloud Run Job Failure: scrape-housing-ads"
#   combiner     = "OR"
#
#   documentation {
#     content   = <<-EOT
#       The Cloud Run job "scrape-housing-ads" has failed.
#       
#       This alert monitors the completed_execution_count metric with 
#       result="failed" label.
#       It catches all types of failures including:
#       - Application errors
#       - OOM (Out of Memory) kills
#       - Container startup failures
#       - Timeout failures
#       
#       Check the Cloud Run logs for details:
#       https://console.cloud.google.com/run/jobs/details/${var.region}/scrape-housing-ads?project=${var.project_id}
#     EOT
#     mime_type = "text/markdown"
#   }
#
#   conditions {
#     display_name = "Job execution failed"
#     condition_threshold {
#       filter = join(" AND ", [
#         "resource.type=\"cloud_run_job\"",
#         "resource.labels.job_name=\"scrape-housing-ads\"",
#         "resource.labels.location=\"${var.region}\"",
#         "metric.type=\"run.googleapis.com/job/completed_execution_count\"",
#         "metric.labels.result=\"failed\""
#       ])
#       duration        = "0s"
#       comparison      = "COMPARISON_GT"
#       threshold_value = 0
#
#       aggregations {
#         alignment_period   = "60s"
#         per_series_aligner = "ALIGN_RATE"
#       }
#     }
#   }
#
#   notification_channels = [
#     google_monitoring_notification_channel.email[0].id
#   ]
#
#   alert_strategy {
#     auto_close = "86400s"
#   }
#
#   depends_on = [
#     google_cloud_run_v2_job.scrape_housing_ads,
#     google_project_service.apis
#   ]
# }

# DISABLED: Uncomment to re-enable
# # Alert policy for sync-regions job failures
# resource "google_monitoring_alert_policy" "sync_regions_failure" {
#   count = data.google_secret_manager_secret_version.alert_email.secret_data != "" ? 1 : 0
#
#   display_name = "Cloud Run Job Failure: sync-regions"
#   combiner     = "OR"
#
#   documentation {
#     content   = <<-EOT
#       The Cloud Run job "sync-regions" has failed.
#       
#       This alert monitors the completed_execution_count metric with 
#       result="failed" label.
#       It catches all types of failures including:
#       - Application errors
#       - OOM (Out of Memory) kills
#       - Container startup failures
#       - Timeout failures
#       
#       Check the Cloud Run logs for details:
#       https://console.cloud.google.com/run/jobs/details/${var.region}/sync-regions?project=${var.project_id}
#     EOT
#     mime_type = "text/markdown"
#   }
#
#   conditions {
#     display_name = "Job execution failed"
#     condition_threshold {
#       filter = join(" AND ", [
#         "resource.type=\"cloud_run_job\"",
#         "resource.labels.job_name=\"sync-regions\"",
#         "resource.labels.location=\"${var.region}\"",
#         "metric.type=\"run.googleapis.com/job/completed_execution_count\"",
#         "metric.labels.result=\"failed\""
#       ])
#       duration        = "0s"
#       comparison      = "COMPARISON_GT"
#       threshold_value = 0
#
#       aggregations {
#         alignment_period   = "60s"
#         per_series_aligner = "ALIGN_RATE"
#       }
#     }
#   }
#
#   notification_channels = [
#     google_monitoring_notification_channel.email[0].id
#   ]
#
#   alert_strategy {
#     auto_close = "86400s"
#   }
#
#   depends_on = [
#     google_cloud_run_v2_job.sync_regions,
#     google_project_service.apis
#   ]
# }

# DISABLED: Uncomment to re-enable
# # Alert policy for sync-housing-regions job failures
# resource "google_monitoring_alert_policy" "sync_housing_regions_failure" {
#   count = data.google_secret_manager_secret_version.alert_email.secret_data != "" ? 1 : 0
#
#   display_name = "Cloud Run Job Failure: sync-housing-regions"
#   combiner     = "OR"
#
#   documentation {
#     content   = <<-EOT
#       The Cloud Run job "sync-housing-regions" has failed.
#       
#       This alert monitors the completed_execution_count metric with 
#       result="failed" label.
#       It catches all types of failures including:
#       - Application errors
#       - OOM (Out of Memory) kills
#       - Container startup failures
#       - Timeout failures
#       
#       Check the Cloud Run logs for details:
#       https://console.cloud.google.com/run/jobs/details/${var.region}/sync-housing-regions?project=${var.project_id}
#     EOT
#     mime_type = "text/markdown"
#   }
#
#   conditions {
#     display_name = "Job execution failed"
#     condition_threshold {
#       filter = join(" AND ", [
#         "resource.type=\"cloud_run_job\"",
#         "resource.labels.job_name=\"sync-housing-regions\"",
#         "resource.labels.location=\"${var.region}\"",
#         "metric.type=\"run.googleapis.com/job/completed_execution_count\"",
#         "metric.labels.result=\"failed\""
#       ])
#       duration        = "0s"
#       comparison      = "COMPARISON_GT"
#       threshold_value = 0
#
#       aggregations {
#         alignment_period   = "60s"
#         per_series_aligner = "ALIGN_RATE"
#       }
#     }
#   }
#
#   notification_channels = [
#     google_monitoring_notification_channel.email[0].id
#   ]
#
#   alert_strategy {
#     auto_close = "86400s"
#   }
#
#   depends_on = [
#     google_cloud_run_v2_job.sync_housing_regions,
#     google_project_service.apis
#   ]
# }

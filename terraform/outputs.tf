output "artifact_registry_repository" {
  value       = google_artifact_registry_repository.dockerhub_cache.name
  description = "Artifact Registry repository id (remote Docker Hub cache)"
}

output "job_runtime_service_account" {
  value       = google_service_account.job_runtime.email
  description = "Service account used by Cloud Run job tasks"
}

output "scheduler_invoker_service_account" {
  value       = google_service_account.scheduler_invoker.email
  description = "Service account Cloud Scheduler uses to invoke jobs"
}

output "cloud_run_job_names" {
  value = [
    google_cloud_run_v2_job.all_jobs.name,
  ]
  description = "Managed Cloud Run jobs (run-migrations is CI-ad-hoc)"
}

output "cloud_scheduler_job_names" {
  value = [
    google_cloud_scheduler_job.all_jobs_daily.name,
  ]
  description = "Cloud Scheduler triggers managed by Terraform"
}

output "job_image_uri" {
  value       = local.job_image
  description = "Image URI in Terraform (CI sets the AR path per SHA)"
}

output "artifact_registry_image_uri" {
  value = join("", [
    "${var.region}-docker.pkg.dev/${var.project_id}/",
    "${local.ar_repo_id}/${var.dockerhub_image}:",
    "${var.image_tag}",
  ])
  description = "Docker Hub pull-through URL (CI uses app repo)"
}

output "ci_container_image_prefix" {
  value = format(
    "%s-docker.pkg.dev/%s/%s/industry-analyser",
    var.region,
    var.project_id,
    google_artifact_registry_repository.app_images.repository_id,
  )
  description = "CI docker push + run jobs update image path (SHA tag)"
}

output "notification_channel_email" {
  value = (
    length(google_monitoring_notification_channel.email) > 0
    ? google_monitoring_notification_channel.email[0].name
    : "Not configured (create secret: industry-analyser-alert-email)"
  )
  description = "Email notification channel for Cloud Run job alerts"
}

output "alert_policies" {
  value = length(google_monitoring_notification_channel.email) > 0 ? [
    google_monitoring_alert_policy.all_jobs_failure[0].name,
    google_monitoring_alert_policy.scrape_item_failure[0].name,
  ] : []
  description = "Alert policies managed by Terraform"
}

output "audio_bucket_name" {
  value       = google_storage_bucket.audio_recordings.name
  description = "GCS bucket for news digest audio clips"
}

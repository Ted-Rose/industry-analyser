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
    google_cloud_run_v2_job.scrape_vacancy.name,
    google_cloud_run_v2_job.scrape_tv_programs.name,
  ]
}

output "cloud_scheduler_job_names" {
  value = [
    google_cloud_scheduler_job.trigger_scrape_vacancy.name,
    google_cloud_scheduler_job.trigger_scrape_tv_programs.name,
  ]
}

output "job_image_uri" {
  value       = local.job_image
  description = "Image URI in Terraform (default public sample job image until overridden; CI sets AR path with commit SHA)"
}

output "artifact_registry_image_uri" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${local.ar_repo_id}/${var.dockerhub_image}:${var.image_tag}"
  description = "Docker Hub pull-through URL (optional; CI uses industry-analyser-app repo)"
}

output "ci_container_image_prefix" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app_images.repository_id}/industry-analyser"
  description = "Image path for CI docker push and gcloud run jobs update (tag with commit SHA)"
}

output "notification_channel_email" {
  value       = length(google_monitoring_notification_channel.email) > 0 ? google_monitoring_notification_channel.email[0].name : "Not configured (create secret: industry-analyser-alert-email)"
  description = "Email notification channel for Cloud Run job failure alerts"
}

output "alert_policies" {
  value = length(google_monitoring_notification_channel.email) > 0 ? [
    google_monitoring_alert_policy.scrape_vacancy_failure[0].name,
    google_monitoring_alert_policy.scrape_tv_programs_failure[0].name,
    google_monitoring_alert_policy.scrape_apartment_ads_failure[0].name,
    google_monitoring_alert_policy.scrape_housing_ads_failure[0].name,
    google_monitoring_alert_policy.sync_regions_failure[0].name,
    google_monitoring_alert_policy.sync_housing_regions_failure[0].name,
  ] : []
  description = "Cloud Run job failure alert policies"
}

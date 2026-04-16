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
  description = "Artifact Registry pull-through URL (used by CI after each build)"
}

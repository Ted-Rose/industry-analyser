#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID=gen-lang-client-0833674612
REGION=europe-north1
SCHED_REGION=europe-west1
RUNTIME_SA=industry-analyser-jobs@${PROJECT_ID}.iam.gserviceaccount.com
SCHED_SA=industry-analyser-scheduler@${PROJECT_ID}.iam.gserviceaccount.com

# --- Enabled APIs (for_each keys) ---
for API in run.googleapis.com cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com iam.googleapis.com \
  cloudresourcemanager.googleapis.com secretmanager.googleapis.com; do
  terraform import "google_project_service.apis[\"${API}\"]" "${PROJECT_ID}/${API}"
done

# --- Artifact Registry repositories ---
terraform import google_artifact_registry_repository.dockerhub_cache \
  "projects/${PROJECT_ID}/locations/${REGION}/repositories/dockerhub-cache"
terraform import google_artifact_registry_repository.app_images \
  "projects/${PROJECT_ID}/locations/${REGION}/repositories/industry-analyser-app"

# --- Service accounts ---
terraform import google_service_account.job_runtime \
  "projects/${PROJECT_ID}/serviceAccounts/${RUNTIME_SA}"
terraform import google_service_account.scheduler_invoker \
  "projects/${PROJECT_ID}/serviceAccounts/${SCHED_SA}"

# --- Project IAM member ---
terraform import google_project_iam_member.job_runtime_ar_reader \
  "${PROJECT_ID} roles/artifactregistry.reader serviceAccount:${RUNTIME_SA}"

# --- Secret Manager IAM members ---
terraform import google_secret_manager_secret_iam_member.fetcher_keywords_accessor \
  "projects/${PROJECT_ID}/secrets/industry-analyser-fetcher-keywords-list roles/secretmanager.secretAccessor serviceAccount:${RUNTIME_SA}"
terraform import google_secret_manager_secret_iam_member.fetcher_portals_accessor \
  "projects/${PROJECT_ID}/secrets/industry-analyser-fetcher-portals roles/secretmanager.secretAccessor serviceAccount:${RUNTIME_SA}"

# --- Cloud Run jobs (existing only) ---
terraform import google_cloud_run_v2_job.scrape_vacancy \
  "projects/${PROJECT_ID}/locations/${REGION}/jobs/scrape-vacancy"
terraform import google_cloud_run_v2_job.scrape_tv_programs \
  "projects/${PROJECT_ID}/locations/${REGION}/jobs/scrape-tv-programs"

# --- Cloud Run job IAM members (existing only) ---
terraform import google_cloud_run_v2_job_iam_member.scheduler_invoker_vacancy \
  "projects/${PROJECT_ID}/locations/${REGION}/jobs/scrape-vacancy roles/run.invoker serviceAccount:${SCHED_SA}"
terraform import google_cloud_run_v2_job_iam_member.scheduler_invoker_tv \
  "projects/${PROJECT_ID}/locations/${REGION}/jobs/scrape-tv-programs roles/run.invoker serviceAccount:${SCHED_SA}"

# --- Cloud Scheduler jobs (existing only) ---
terraform import google_cloud_scheduler_job.trigger_scrape_vacancy \
  "projects/${PROJECT_ID}/locations/${SCHED_REGION}/jobs/trigger-scrape-vacancy"
terraform import google_cloud_scheduler_job.trigger_scrape_tv_programs \
  "projects/${PROJECT_ID}/locations/${SCHED_REGION}/jobs/trigger-scrape-tv-programs"

echo "Import complete. Run 'terraform plan' to verify."

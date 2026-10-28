locals {
  ar_repo_id = "dockerhub-cache"
  # Cloud Run validates the image at job create time. The AR remote cache has no tag until
  # a pull happens, and your Docker Hub tag may not exist yet — so default to a public
  # image that always resolves. GitHub Actions immediately updates both jobs to your image.
  job_image = trimspace(var.container_image) != "" ? trimspace(var.container_image) : "us-docker.pkg.dev/cloudrun/container/job:latest"
}

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "secretmanager.googleapis.com",
    "monitoring.googleapis.com",
  ])

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "dockerhub_cache" {
  location      = var.region
  repository_id = local.ar_repo_id
  description   = "Docker Hub pull-through cache (optional mirror; CI pushes to industry-analyser-app)"
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"

  remote_repository_config {
    docker_repository {
      public_repository = "DOCKER_HUB"
    }
  }

  cleanup_policies {
    id     = "keep-latest-3"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }

  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"
    condition {
      tag_state = "UNTAGGED"
    }
  }

  depends_on = [google_project_service.apis]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_artifact_registry_repository" "app_images" {
  location      = var.region
  repository_id = "industry-analyser-app"
  description   = "Container images built and pushed from GitHub Actions - Cost Optimized"
  format        = "DOCKER"

  # 1. DELETE Policy: Target ALL images older than 1 day
  cleanup_policies {
    id     = "delete-old-versions"
    action = "DELETE"
    condition {
      tag_state  = "ANY"
      older_than = "86400s" # 24 Hours
    }
  }

  # 2. KEEP Policy: Protect the most recent 3 versions from deletion
  cleanup_policies {
    id     = "keep-latest-3"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }

  depends_on = [google_project_service.apis]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "job_runtime" {
  account_id   = "industry-analyser-jobs"
  display_name = "Industry Analyser Cloud Run Jobs"
  project      = var.project_id

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "scheduler_invoker" {
  account_id   = "industry-analyser-scheduler"
  display_name = "Industry Analyser Cloud Scheduler (Run Job invoker)"
  project      = var.project_id

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_project_iam_member" "job_runtime_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.job_runtime.email}"
}

# All runtime config ships in one Secret Manager secret `env-file`
# (payload = full .env file, injected as the DOTENV env var).
# Created outside Terraform with gcloud.
resource "google_secret_manager_secret_iam_member" "env_file_accessor" {
  project   = var.project_id
  secret_id = "env-file"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.job_runtime.email}"
}

# Master job: runs `python manage.py run_all_jobs`, which executes the
# enabled sub-jobs in scrape_jobs/management/commands/run_all_jobs.py
# sequentially. Timeout covers the worst-case scheduled pass —
# sync_receipt_emails (1,800s) plus the three 8,000s scrapers can all
# be due on one day (e.g. an odd Monday that ends a month) = 25,800s,
# leaving headroom under 36,000s. `manual` entries (scrape_vacancy,
# link_ads_to_properties) run only alone via `--only`, so they never
# stack onto a scheduled pass.
#
# The JOBS list in run_all_jobs.py is the single place jobs are now
# enabled/disabled — the six former per-task Cloud Run jobs
# (scrape-vacancy, scrape-tv-programs, scrape-apartment-ads,
# scrape-housing-ads, link-ads-to-properties, sync-receipt-emails),
# their invoker bindings, scheduler triggers and the commented-out
# sync-*-regions blocks were all removed in Phase 2 of the Cloud Run
# job consolidation.
resource "google_cloud_run_v2_job" "all_jobs" {
  name     = "all-jobs"
  location = var.region

  template {
    task_count = 1
    template {
      timeout         = "36000s"
      max_retries     = 0
      service_account = google_service_account.job_runtime.email

      containers {
        image = local.job_image
        # Keep command/args split matching what CI's
        # `gcloud run jobs update --command=python
        # --args=manage.py,run_all_jobs` writes, so plan shows no
        # perpetual in-place drift on this job.
        command = ["python"]
        args    = ["manage.py", "run_all_jobs"]

        # Single consolidated secret: payload is the full .env file,
        # loaded by settings.py via the DOTENV env var.
        env {
          name = "DOTENV"
          value_source {
            secret_key_ref {
              secret  = "env-file"
              version = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
    }
  }

  depends_on = [
    google_artifact_registry_repository.dockerhub_cache,
    google_project_service.apis,
    google_secret_manager_secret_iam_member.env_file_accessor,
  ]

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      # gcloud-stamped annotations rewritten by every
      # `gcloud run jobs update` in CI — keep them out of plan diffs.
      client,
      client_version,
    ]
    prevent_destroy = true
  }
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_all_jobs" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.all_jobs.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_scheduler_job" "all_jobs_daily" {
  name             = "all-jobs-daily"
  description      = "Run all-jobs master job daily; per-job gating in run_all_jobs JOBS list"
  schedule         = "50 19 * * *"
  time_zone        = "Etc/UTC"
  region           = var.scheduler_region
  attempt_deadline = "600s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.all_jobs.name}:run"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  depends_on = [
    google_cloud_run_v2_job.all_jobs,
    google_cloud_run_v2_job_iam_member.scheduler_invoker_all_jobs,
    google_project_service.apis,
  ]
}

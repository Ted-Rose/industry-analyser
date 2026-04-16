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
  ])

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "dockerhub_cache" {
  location      = var.region
  repository_id = local.ar_repo_id
  description   = "Docker Hub pull-through cache for industry-analyser images"
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"

  remote_repository_config {
    docker_repository {
      public_repository = "DOCKER_HUB"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "job_runtime" {
  account_id   = "industry-analyser-jobs"
  display_name = "Industry Analyser Cloud Run Jobs"
  project      = var.project_id
}

resource "google_service_account" "scheduler_invoker" {
  account_id   = "industry-analyser-scheduler"
  display_name = "Industry Analyser Cloud Scheduler (Run Job invoker)"
  project      = var.project_id
}

resource "google_project_iam_member" "job_runtime_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.job_runtime.email}"
}

resource "google_cloud_run_v2_job" "scrape_vacancy" {
  name     = "scrape-vacancy"
  location = var.region

  template {
    task_count = 1
    template {
      timeout         = "10800s"
      max_retries     = 0
      service_account = google_service_account.job_runtime.email

      containers {
        image   = local.job_image
        command = ["python", "manage.py", "scrape_first_vacancy_portal"]

        env {
          name  = "DEBUG"
          value = "False"
        }
        env {
          name  = "SECRET_KEY"
          value = var.secret_key
        }
        env {
          name  = "DATABASE_URL"
          value = var.database_url
        }
        env {
          name  = "BASE_URL"
          value = var.base_url
        }
        env {
          name  = "DB_SSL_CERT"
          value = var.db_ssl_cert
        }
        env {
          name  = "HARD_CODED_PASSWORD"
          value = var.hard_coded_password
        }
        env {
          name  = "GEMINI_API_KEY"
          value = var.gemini_api_key
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
  ]
}

resource "google_cloud_run_v2_job" "scrape_tv_programs" {
  name     = "scrape-tv-programs"
  location = var.region

  template {
    task_count = 1
    template {
      timeout         = "10800s"
      max_retries     = 0
      service_account = google_service_account.job_runtime.email

      containers {
        image   = local.job_image
        command = ["python", "manage.py", "scrape_tv_programs"]

        env {
          name  = "DEBUG"
          value = "False"
        }
        env {
          name  = "SECRET_KEY"
          value = var.secret_key
        }
        env {
          name  = "DATABASE_URL"
          value = var.database_url
        }
        env {
          name  = "BASE_URL"
          value = var.base_url
        }
        env {
          name  = "DB_SSL_CERT"
          value = var.db_ssl_cert
        }
        env {
          name  = "HARD_CODED_PASSWORD"
          value = var.hard_coded_password
        }
        env {
          name  = "GEMINI_API_KEY"
          value = var.gemini_api_key
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
  ]
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_vacancy" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.scrape_vacancy.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_tv" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.scrape_tv_programs.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_scheduler_job" "trigger_scrape_vacancy" {
  name             = "trigger-scrape-vacancy"
  description      = "Run scrape-vacancy job every 48h (02:00 UTC)"
  schedule         = "0 2 */2 * *"
  time_zone        = "Etc/UTC"
  region           = var.scheduler_region
  attempt_deadline = "600s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.scrape_vacancy.name}:run"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  depends_on = [
    google_cloud_run_v2_job.scrape_vacancy,
    google_project_service.apis,
  ]
}

resource "google_cloud_scheduler_job" "trigger_scrape_tv_programs" {
  name             = "trigger-scrape-tv-programs"
  description      = "Run scrape-tv-programs job every 48h (03:00 UTC)"
  schedule         = "0 3 */2 * *"
  time_zone        = "Etc/UTC"
  region           = var.scheduler_region
  attempt_deadline = "600s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.scrape_tv_programs.name}:run"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  depends_on = [
    google_cloud_run_v2_job.scrape_tv_programs,
    google_project_service.apis,
  ]
}

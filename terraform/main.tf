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
  description   = "Container images built and pushed from GitHub Actions"
  format        = "DOCKER"

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

# Fetcher portal config (Secret Manager, secrets created outside Terraform with gcloud)
resource "google_secret_manager_secret_iam_member" "fetcher_keywords_accessor" {
  project   = var.project_id
  secret_id = "industry-analyser-fetcher-keywords-list"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.job_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "fetcher_portals_accessor" {
  project   = var.project_id
  secret_id = "industry-analyser-fetcher-portals"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.job_runtime.email}"
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
        image = local.job_image
        command = [
          "python3",
          "scripts/materialize_fetcher_config_and_scrape.py",
        ]

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

        env {
          name = "FETCHER_KEYWORDS_LIST_JSON"
          value_source {
            secret_key_ref {
              secret  = "industry-analyser-fetcher-keywords-list"
              version = "latest"
            }
          }
        }

        env {
          name = "FETCHER_PORTALS_JSON"
          value_source {
            secret_key_ref {
              secret  = "industry-analyser-fetcher-portals"
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
    google_secret_manager_secret_iam_member.fetcher_keywords_accessor,
    google_secret_manager_secret_iam_member.fetcher_portals_accessor,
  ]

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
    prevent_destroy = true
  }
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

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
    prevent_destroy = true
  }
}

resource "google_cloud_run_v2_job" "scrape_apartment_ads" {
  name     = "scrape-apartment-ads"
  location = var.region

  template {
    task_count = 1
    template {
      timeout         = "21600s"
      max_retries     = 2
      service_account = google_service_account.job_runtime.email

      containers {
        image   = local.job_image
        command = ["python", "manage.py", "scrape_apartment_ads"]

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

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
    prevent_destroy = true
  }
}

resource "google_cloud_run_v2_job" "scrape_housing_ads" {
  name     = "scrape-housing-ads"
  location = var.region

  template {
    task_count = 1
    template {
      timeout         = "21600s"
      max_retries     = 2
      service_account = google_service_account.job_runtime.email

      containers {
        image   = local.job_image
        command = ["python", "manage.py", "scrape_housing_ads"]

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

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
    prevent_destroy = true
  }
}

resource "google_cloud_run_v2_job" "sync_regions" {
  name     = "sync-regions"
  location = var.region

  template {
    task_count = 1
    template {
      timeout         = "1800s"
      max_retries     = 0
      service_account = google_service_account.job_runtime.email

      containers {
        image   = local.job_image
        command = ["python", "manage.py", "sync_apartment_regions"]

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

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
    prevent_destroy = true
  }
}

resource "google_cloud_run_v2_job" "sync_housing_regions" {
  name     = "sync-housing-regions"
  location = var.region

  template {
    task_count = 1
    template {
      timeout         = "1800s"
      max_retries     = 0
      service_account = google_service_account.job_runtime.email

      containers {
        image   = local.job_image
        command = ["python", "manage.py", "sync_housing_regions"]

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

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
    prevent_destroy = true
  }
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_sync_regions" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.sync_regions.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_sync_housing_regions" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.sync_housing_regions.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_scheduler_job" "trigger_sync_regions" {
  name             = "trigger-sync-regions"
  description      = "Sync ss.com regions to DB weekly (Sunday 01:00 UTC)"
  schedule         = "0 1 * * 0"
  time_zone        = "Etc/UTC"
  region           = var.scheduler_region
  attempt_deadline = "600s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.sync_regions.name}:run"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  depends_on = [
    google_cloud_run_v2_job.sync_regions,
    google_project_service.apis,
  ]
}

resource "google_cloud_scheduler_job" "trigger_sync_housing_regions" {
  name             = "trigger-sync-housing-regions"
  description      = "Sync ss.com housing regions to DB weekly (Sunday 01:30 UTC)"
  schedule         = "30 1 * * 0"
  time_zone        = "Etc/UTC"
  region           = var.scheduler_region
  attempt_deadline = "600s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.sync_housing_regions.name}:run"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  depends_on = [
    google_cloud_run_v2_job.sync_housing_regions,
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

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_apartment_ads" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.scrape_apartment_ads.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_housing_ads" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.scrape_housing_ads.name
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

resource "google_cloud_scheduler_job" "trigger_scrape_apartment_ads" {
  name             = "trigger-scrape-apartment-ads"
  description      = "Run scrape-apartment-ads job daily (04:00 UTC)"
  schedule         = "0 4 * * *"
  time_zone        = "Etc/UTC"
  region           = var.scheduler_region
  attempt_deadline = "600s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.scrape_apartment_ads.name}:run"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  depends_on = [
    google_cloud_run_v2_job.scrape_apartment_ads,
    google_project_service.apis,
  ]
}

resource "google_cloud_scheduler_job" "trigger_scrape_housing_ads" {
  name             = "trigger-scrape-housing-ads"
  description      = "Run scrape-housing-ads job daily (02:00 UTC)"
  schedule         = "0 2 * * *"
  time_zone        = "Etc/UTC"
  region           = var.scheduler_region
  attempt_deadline = "600s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.scrape_housing_ads.name}:run"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  depends_on = [
    google_cloud_run_v2_job.scrape_housing_ads,
    google_project_service.apis,
  ]
}

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

resource "google_cloud_run_v2_job" "scrape_vacancy" {
  name     = "scrape-vacancy"
  location = var.region

  template {
    task_count = 1
    template {
      timeout         = "8000s"
      max_retries     = 0
      service_account = google_service_account.job_runtime.email

      containers {
        image = local.job_image
        command = [
          "python3",
          "scripts/materialize_fetcher_config_and_scrape.py",
        ]

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
      timeout         = "8000s"
      max_retries     = 0
      service_account = google_service_account.job_runtime.email

      containers {
        image   = local.job_image
        command = ["python", "manage.py", "scrape_tv_programs"]

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
      timeout         = "8000s"
      max_retries     = 0
      service_account = google_service_account.job_runtime.email

      containers {
        image   = local.job_image
        command = ["python", "manage.py", "scrape_apartment_ads"]

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
      timeout         = "8000s"
      max_retries     = 1
      service_account = google_service_account.job_runtime.email

      containers {
        image   = local.job_image
        command = ["python", "manage.py", "scrape_housing_ads"]

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
  ]

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
    prevent_destroy = true
  }
}

# Removed to stay within the 3-free-jobs Cloud Scheduler quota
# ($0.10/job/mo beyond 3 per billing account).
# Uncomment to re-enable.
# resource "google_cloud_run_v2_job" "sync_apartment_regions" {
#   name     = "sync-apartment-regions"
#   location = var.region
#
#   template {
#     task_count = 1
#     template {
#       timeout         = "1800s"
#       max_retries     = 0
#       service_account = google_service_account.job_runtime.email
#
#       containers {
#         image   = local.job_image
#         command = ["python", "manage.py", "sync_apartment_regions"]
#
#         # Single consolidated secret: payload is the full .env file,
#         # loaded by settings.py via the DOTENV env var.
#         env {
#           name = "DOTENV"
#           value_source {
#             secret_key_ref {
#               secret  = "env-file"
#               version = "latest"
#             }
#           }
#         }
#
#         resources {
#           limits = {
#             cpu    = "1"
#             memory = "512Mi"
#           }
#         }
#       }
#     }
#   }
#
#   depends_on = [
#     google_artifact_registry_repository.dockerhub_cache,
#     google_project_service.apis,
#   ]
#
#   lifecycle {
#     ignore_changes = [
#       template[0].template[0].containers[0].image,
#     ]
#     prevent_destroy = true
#   }
# }
#
# resource "google_cloud_run_v2_job" "sync_housing_regions" {
#   name     = "sync-housing-regions"
#   location = var.region
#
#   template {
#     task_count = 1
#     template {
#       timeout         = "1800s"
#       max_retries     = 0
#       service_account = google_service_account.job_runtime.email
#
#       containers {
#         image   = local.job_image
#         command = ["python", "manage.py", "sync_housing_regions"]
#
#         # Single consolidated secret: payload is the full .env file,
#         # loaded by settings.py via the DOTENV env var.
#         env {
#           name = "DOTENV"
#           value_source {
#             secret_key_ref {
#               secret  = "env-file"
#               version = "latest"
#             }
#           }
#         }
#
#         resources {
#           limits = {
#             cpu    = "1"
#             memory = "512Mi"
#           }
#         }
#       }
#     }
#   }
#
#   depends_on = [
#     google_artifact_registry_repository.dockerhub_cache,
#     google_project_service.apis,
#   ]
#
#   lifecycle {
#     ignore_changes = [
#       template[0].template[0].containers[0].image,
#     ]
#     prevent_destroy = true
#   }
# }
#
# resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_sync_apartment_regions" {
#   project  = var.project_id
#   location = var.region
#   name     = google_cloud_run_v2_job.sync_apartment_regions.name
#   role     = "roles/run.invoker"
#   member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
# }
#
# resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_sync_housing_regions" {
#   project  = var.project_id
#   location = var.region
#   name     = google_cloud_run_v2_job.sync_housing_regions.name
#   role     = "roles/run.invoker"
#   member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
# }
#
# resource "google_cloud_scheduler_job" "trigger_sync_apartment_regions" {
#   name             = "trigger-sync-apartment-regions"
#   description      = "Sync ss.com apartment regions to DB monthly (1st day 20:50 UTC)"
#   schedule         = "50 20 1 * *"
#   time_zone        = "Etc/UTC"
#   region           = var.scheduler_region
#   attempt_deadline = "600s"
#
#   http_target {
#     http_method = "POST"
#     uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.sync_apartment_regions.name}:run"
#     body        = base64encode("{}")
#
#     oauth_token {
#       service_account_email = google_service_account.scheduler_invoker.email
#     }
#   }
#
#   depends_on = [
#     google_cloud_run_v2_job.sync_apartment_regions,
#     google_project_service.apis,
#   ]
# }
#
# resource "google_cloud_scheduler_job" "trigger_sync_housing_regions" {
#   name             = "trigger-sync-housing-regions"
#   description      = "Sync ss.com housing regions to DB monthly (1st day 21:20 UTC)"
#   schedule         = "20 21 1 * *"
#   time_zone        = "Etc/UTC"
#   region           = var.scheduler_region
#   attempt_deadline = "600s"
#
#   http_target {
#     http_method = "POST"
#     uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.sync_housing_regions.name}:run"
#     body        = base64encode("{}")
#
#     oauth_token {
#       service_account_email = google_service_account.scheduler_invoker.email
#     }
#   }
#
#   depends_on = [
#     google_cloud_run_v2_job.sync_housing_regions,
#     google_project_service.apis,
#   ]
# }

# DISABLED: Uncomment to re-enable
# resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_vacancy" {
#   project  = var.project_id
#   location = var.region
#   name     = google_cloud_run_v2_job.scrape_vacancy.name
#   role     = "roles/run.invoker"
#   member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
# }

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

# DISABLED: Uncomment to re-enable
# resource "google_cloud_scheduler_job" "trigger_scrape_vacancy" {
#   name             = "trigger-scrape-vacancy"
#   description      = "Run scrape-vacancy job weekly (Mon 20:50 UTC)"
#   schedule         = "50 20 * * 1"
#   time_zone        = "Etc/UTC"
#   region           = var.scheduler_region
#   attempt_deadline = "600s"
#
#   http_target {
#     http_method = "POST"
#     uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.scrape_vacancy.name}:run"
#     body        = base64encode("{}")
#
#     oauth_token {
#       service_account_email = google_service_account.scheduler_invoker.email
#     }
#   }
#
#   depends_on = [
#     google_cloud_run_v2_job.scrape_vacancy,
#     google_project_service.apis,
#   ]
# }

resource "google_cloud_scheduler_job" "trigger_scrape_tv_programs" {
  name             = "trigger-scrape-tv-programs"
  description      = "Run scrape-tv-programs job every 48h (20:50 UTC)"
  schedule         = "50 20 */2 * *"
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
  description      = "Run scrape-apartment-ads job weekly (Mon 21:30 UTC)"
  schedule         = "30 21 * * 1"
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
  description      = "Run scrape-housing-ads job weekly (Mon 20:50 UTC)"
  schedule         = "50 20 * * 1"
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

resource "google_cloud_run_v2_job" "link_ads_to_properties" {
  name     = "link-ads-to-properties"
  location = var.region

  template {
    task_count = 1
    template {
      timeout         = "3600s"
      max_retries     = 0
      service_account = google_service_account.job_runtime.email

      containers {
        image = local.job_image
        command = [
          "python",
          "manage.py",
          "link_ads_to_properties",
          "--older-than-days",
          "3",
        ]

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
  ]

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
    prevent_destroy = true
  }
}
# No Cloud Scheduler trigger on purpose: the job is visible in GCP and
# run manually via `gcloud run jobs execute link-ads-to-properties`.

resource "google_cloud_run_v2_job" "sync_receipt_emails" {
  name     = "sync-receipt-emails"
  location = var.region

  template {
    task_count = 1
    template {
      timeout         = "1800s"
      max_retries     = 0
      service_account = google_service_account.job_runtime.email

      containers {
        image = local.job_image
        # --last-day-only guards the days 28-31 trigger below so the
        # job actually runs only on the last day of the month.
        command = [
          "python",
          "manage.py",
          "sync_receipt_emails",
          "--last-day-only",
        ]

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
    ]
    prevent_destroy = true
  }
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker_receipts" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.sync_receipt_emails.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_scheduler_job" "trigger_sync_receipt_emails" {
  name             = "trigger-sync-receipt-emails"
  description      = "Poll receipt collector inbox on the last day of each month (19:50 UTC — an hour before the other jobs, for free-tier Gemini quota)"
  schedule         = "50 19 28-31 * *"
  time_zone        = "Etc/UTC"
  region           = var.scheduler_region
  attempt_deadline = "600s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.sync_receipt_emails.name}:run"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  depends_on = [
    google_cloud_run_v2_job.sync_receipt_emails,
    google_project_service.apis,
  ]
}

# Master job: runs `python manage.py run_all_jobs`, which executes the
# enabled sub-jobs in scrape_jobs/management/commands/run_all_jobs.py
# sequentially. Timeout covers the worst-case scheduled pass —
# sync_receipt_emails (1,800s) plus the three 8,000s scrapers can all
# be due on one day (e.g. an odd Monday that ends a month) = 25,800s,
# leaving headroom under 36,000s. `manual` entries (scrape_vacancy,
# link_ads_to_properties) run only alone via `--only`, so they never
# stack onto a scheduled pass.
# No Cloud Scheduler trigger in Phase 1 — run manually via
# `gcloud run jobs execute all-jobs`.
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
        image   = local.job_image
        command = ["python", "manage.py", "run_all_jobs"]

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
    ]
    prevent_destroy = true
  }
}

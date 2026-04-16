variable "project_id" {
  type        = string
  description = "GCP project ID"
  default     = "gen-lang-client-0833674612"
}

variable "region" {
  type        = string
  description = "Region for Cloud Run Jobs and Artifact Registry"
  default     = "europe-north1"
}

variable "scheduler_region" {
  type        = string
  description = "Cloud Scheduler region (must be a Scheduler-supported location; europe-north1 is not valid for Scheduler)"
  default     = "europe-west1"
}

variable "image_tag" {
  type        = string
  description = "Docker image tag (must exist on Docker Hub under tedisrozenfelds/industry-analyser)"
  default     = "latest"
}

variable "dockerhub_image" {
  type        = string
  description = "Docker Hub path after the remote repository (namespace/image)"
  default     = "tedisrozenfelds/industry-analyser"
}

variable "container_image" {
  type        = string
  description = "Full container image URI for both jobs. Leave empty to use a public Cloud Run sample image so the first terraform apply succeeds; GitHub Actions then updates jobs to the Artifact Registry pull-through URL with the commit SHA tag."
  default     = ""
}

variable "secret_key" {
  type        = string
  description = "Django SECRET_KEY"
  sensitive   = true
}

variable "database_url" {
  type        = string
  description = "Postgres DATABASE_URL"
  sensitive   = true
}

variable "base_url" {
  type        = string
  description = "Django BASE_URL"
  sensitive   = true
}

variable "db_ssl_cert" {
  type        = string
  description = "Aiven or other CA PEM for Postgres (full certificate text)"
  sensitive   = true
}

variable "hard_coded_password" {
  type        = string
  description = "Optional HARD_CODED_PASSWORD"
  default     = ""
  sensitive   = true
}

variable "gemini_api_key" {
  type        = string
  description = "Optional GEMINI_API_KEY"
  default     = ""
  sensitive   = true
}

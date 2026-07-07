terraform {
  required_version = ">= 1.3"

  backend "gcs" {
    bucket = "gen-lang-client-0833674612-terraform-state"
    prefix = "terraform/state"
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.45"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

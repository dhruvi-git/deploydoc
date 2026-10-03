terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  # bucket is passed at init time: terraform init -backend-config="bucket=<name>"
  backend "gcs" {
    prefix = "deploydoc-target"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

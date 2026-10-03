locals {
  env = merge(
    { APP_VERSION = var.app_version },
    var.database_url == "" ? {} : { DATABASE_URL = var.database_url }
  )
}

resource "google_cloud_run_v2_service" "target" {
  name                = "deploydoc-target"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.image
      ports {
        container_port = var.container_port
      }
      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }
      dynamic "env" {
        for_each = local.env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = google_cloud_run_v2_service.target.project
  location = google_cloud_run_v2_service.target.location
  name     = google_cloud_run_v2_service.target.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Messer data plane on Google Cloud (EU): VPC, private GKE (workload identity, CMEK for secrets), Cloud SQL for
# PostgreSQL 16 (pgvector) on a private IP, Memorystore for Redis (TLS + AUTH), Cloud Storage (CMEK) and Cloud KMS.

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  labels = merge(var.labels, { "messer-component" = "data-plane", "messer-name" = var.name })
}

resource "google_project_service" "apis" {
  for_each = toset([
    "compute.googleapis.com",
    "container.googleapis.com",
    "sqladmin.googleapis.com",
    "servicenetworking.googleapis.com",
    "redis.googleapis.com",
    "cloudkms.googleapis.com",
    "storage.googleapis.com",
    "file.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ----------------------------------------------------------------------------- KMS

resource "google_kms_key_ring" "this" {
  name       = var.name
  location   = var.region
  depends_on = [google_project_service.apis]
}

resource "google_kms_crypto_key" "data" {
  name            = "${var.name}-data"
  key_ring        = google_kms_key_ring.this.id
  rotation_period = "7776000s" # 90 days

  lifecycle {
    prevent_destroy = false
  }
}

# Service agents that encrypt with the key.
resource "google_project_service_identity" "sql" {
  provider = google-beta
  project  = var.project_id
  service  = "sqladmin.googleapis.com"
}

data "google_storage_project_service_account" "gcs" {}

resource "google_kms_crypto_key_iam_member" "agents" {
  for_each = {
    gke   = "serviceAccount:service-${data.google_project.this.number}@container-engine-robot.iam.gserviceaccount.com"
    sql   = "serviceAccount:${google_project_service_identity.sql.email}"
    gcs   = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
    redis = "serviceAccount:service-${data.google_project.this.number}@cloud-redis.iam.gserviceaccount.com"
  }
  crypto_key_id = google_kms_crypto_key.data.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = each.value
}

# ----------------------------------------------------------------------------- network

resource "google_compute_network" "this" {
  name                    = var.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "this" {
  name                     = var.name
  region                   = var.region
  network                  = google_compute_network.this.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.pods_cidr
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.services_cidr
  }
}

resource "google_compute_router" "this" {
  name    = var.name
  region  = var.region
  network = google_compute_network.this.id
}

resource "google_compute_router_nat" "this" {
  name                               = var.name
  router                             = google_compute_router.this.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_global_address" "private_services" {
  name          = "${var.name}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.this.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.this.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

# ----------------------------------------------------------------------------- GKE

resource "google_service_account" "nodes" {
  account_id   = "${var.name}-nodes"
  display_name = "Messer data plane GKE nodes"
}

resource "google_project_iam_member" "nodes" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/monitoring.viewer",
    "roles/artifactregistry.reader",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.nodes.email}"
}

resource "google_container_cluster" "this" {
  name                     = var.name
  location                 = var.region
  network                  = google_compute_network.this.id
  subnetwork               = google_compute_subnetwork.this.id
  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = var.deletion_protection
  resource_labels          = local.labels

  release_channel {
    channel = "REGULAR"
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = length(var.master_authorized_cidrs) == 0
    master_ipv4_cidr_block  = var.master_cidr
  }

  dynamic "master_authorized_networks_config" {
    for_each = length(var.master_authorized_cidrs) > 0 ? [1] : []
    content {
      dynamic "cidr_blocks" {
        for_each = var.master_authorized_cidrs
        content {
          cidr_block = cidr_blocks.value
        }
      }
    }
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  database_encryption {
    state    = "ENCRYPTED"
    key_name = google_kms_crypto_key.data.id
  }

  network_policy {
    enabled  = true
    provider = "CALICO"
  }

  addons_config {
    network_policy_config {
      disabled = false
    }
    gcp_filestore_csi_driver_config {
      enabled = true
    }
  }

  depends_on = [google_kms_crypto_key_iam_member.agents]
}

resource "google_container_node_pool" "default" {
  name     = "default"
  location = var.region
  cluster  = google_container_cluster.this.name

  autoscaling {
    min_node_count = var.node_min_count
    max_node_count = var.node_max_count
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = var.node_machine_type
    service_account = google_service_account.nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = local.labels

    shielded_instance_config {
      enable_secure_boot = true
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }
}

# Workload identity for the chart's service account.
resource "google_service_account" "workload" {
  account_id   = "${var.name}-workload"
  display_name = "Messer data plane workloads"
}

resource "google_service_account_iam_member" "workload_identity" {
  service_account_id = google_service_account.workload.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.kubernetes_namespace}/${var.kubernetes_service_account}]"
}

# ----------------------------------------------------------------------------- Cloud SQL (PostgreSQL 16 + pgvector)

resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "postgres" {
  name                = var.name
  region              = var.region
  database_version    = "POSTGRES_16"
  encryption_key_name = google_kms_crypto_key.data.id
  deletion_protection = var.deletion_protection

  settings {
    tier              = var.postgres_tier
    availability_type = var.postgres_high_availability ? "REGIONAL" : "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = var.postgres_disk_gb
    disk_autoresize   = true
    user_labels       = local.labels

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.this.id
      ssl_mode                                      = "ENCRYPTED_ONLY"
      enable_private_path_for_google_cloud_services = true
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "02:00"
      backup_retention_settings {
        retained_backups = 14
      }
    }

    maintenance_window {
      day  = 7
      hour = 3
    }

    insights_config {
      query_insights_enabled = true
    }
  }

  depends_on = [google_service_networking_connection.private_services, google_kms_crypto_key_iam_member.agents]
}

resource "google_sql_database" "messer" {
  name     = "messer"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "messer" {
  name     = "messer"
  instance = google_sql_database_instance.postgres.name
  password = random_password.postgres.result
}

# ----------------------------------------------------------------------------- Memorystore for Redis

resource "google_redis_instance" "this" {
  name                    = var.name
  region                  = var.region
  tier                    = "STANDARD_HA"
  memory_size_gb          = var.redis_memory_gb
  redis_version           = "REDIS_7_2"
  authorized_network      = google_compute_network.this.id
  connect_mode            = "PRIVATE_SERVICE_ACCESS"
  auth_enabled            = true
  transit_encryption_mode = "SERVER_AUTHENTICATION"
  customer_managed_key    = google_kms_crypto_key.data.id
  labels                  = local.labels

  depends_on = [google_service_networking_connection.private_services, google_kms_crypto_key_iam_member.agents]
}

# ----------------------------------------------------------------------------- Cloud Storage

resource "google_storage_bucket" "storage" {
  name                        = "${var.project_id}-${var.name}-storage"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = !var.deletion_protection
  labels                      = local.labels

  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = google_kms_crypto_key.data.id
  }

  depends_on = [google_kms_crypto_key_iam_member.agents]
}

resource "google_storage_bucket_iam_member" "workload" {
  bucket = google_storage_bucket.storage.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.workload.email}"
}

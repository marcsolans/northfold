output "region" {
  value = var.region
}

output "cluster_name" {
  description = "GKE cluster (gcloud container clusters get-credentials <cluster_name> --region <region>)."
  value       = google_container_cluster.this.name
}

output "workload_service_account" {
  description = "Annotate the chart's service account: iam.gke.io/gcp-service-account=<this value>."
  value       = google_service_account.workload.email
}

output "kms_key" {
  value = google_kms_crypto_key.data.id
}

output "storage_bucket" {
  value = google_storage_bucket.storage.name
}

output "postgres_private_ip" {
  value = google_sql_database_instance.postgres.private_ip_address
}

output "redis_host" {
  value = google_redis_instance.this.host
}

output "database_url" {
  description = "Owner connection (migrations)."
  value       = "postgresql+psycopg://messer:${random_password.postgres.result}@${google_sql_database_instance.postgres.private_ip_address}:5432/messer?sslmode=require"
  sensitive   = true
}

output "redis_url" {
  value     = "rediss://:${google_redis_instance.this.auth_string}@${google_redis_instance.this.host}:${google_redis_instance.this.port}/0"
  sensitive = true
}

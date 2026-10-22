output "resource_group" {
  value = azurerm_resource_group.this.name
}

output "cluster_name" {
  description = "AKS cluster (az aks get-credentials -g <resource_group> -n <cluster_name>)."
  value       = azurerm_kubernetes_cluster.this.name
}

output "workload_client_id" {
  description = "Annotate the chart's service account: azure.workload.identity/client-id=<this value>."
  value       = azurerm_user_assigned_identity.workload.client_id
}

output "key_vault_uri" {
  value = azurerm_key_vault.this.vault_uri
}

output "storage_account" {
  value = azurerm_storage_account.this.name
}

output "postgres_host" {
  value = azurerm_postgresql_flexible_server.this.fqdn
}

output "redis_host" {
  value = azurerm_redis_cache.this.hostname
}

output "database_url" {
  description = "Owner connection (migrations)."
  value       = "postgresql+psycopg://messer:${random_password.postgres.result}@${azurerm_postgresql_flexible_server.this.fqdn}:5432/messer?sslmode=require"
  sensitive   = true
}

output "redis_url" {
  value     = "rediss://:${azurerm_redis_cache.this.primary_access_key}@${azurerm_redis_cache.this.hostname}:${azurerm_redis_cache.this.ssl_port}/0"
  sensitive = true
}

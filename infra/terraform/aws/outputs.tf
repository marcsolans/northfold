output "region" {
  value = var.region
}

output "cluster_name" {
  description = "EKS cluster (aws eks update-kubeconfig --name <cluster_name> --region <region>)."
  value       = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  value = aws_eks_cluster.this.endpoint
}

output "workload_role_arn" {
  description = "Annotate the chart's service account: eks.amazonaws.com/role-arn=<this value>."
  value       = aws_iam_role.workload.arn
}

output "kms_key_arn" {
  value = aws_kms_key.this.arn
}

output "storage_bucket" {
  value = aws_s3_bucket.storage.bucket
}

output "efs_file_system_id" {
  description = "EFS file system for the chart's ReadWriteMany volume (EFS CSI StorageClass fileSystemId)."
  value       = aws_efs_file_system.projects.id
}

output "postgres_host" {
  value = aws_db_instance.postgres.address
}

output "redis_host" {
  value = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "database_url" {
  description = "Owner connection (migrations). Create the messer_app/messer_readonly roles with `make migrate`."
  value       = "postgresql+psycopg://messer:${random_password.postgres.result}@${aws_db_instance.postgres.address}:5432/messer?sslmode=require"
  sensitive   = true
}

output "redis_url" {
  value     = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0"
  sensitive = true
}

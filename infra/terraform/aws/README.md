# Messer data plane — AWS (EU)

Creates everything the [`messer-data-plane`](../../helm/messer-data-plane) chart needs in **your** AWS account,
in an EU region (`eu-central-1` by default; non-EU regions are rejected by validation):

| Resource | Details |
|---|---|
| Network | VPC with private and public subnets in 3 AZs, one NAT gateway, S3 gateway endpoint. Data services only accept traffic from the VPC. |
| Kubernetes | EKS (private endpoint; public only for `cluster_public_access_cidrs`), managed node group, secrets encrypted with KMS, EFS CSI add-on, IRSA OIDC provider. |
| Workload identity | IAM role for the chart's service account: S3 bucket, KMS key and `bedrock:InvokeModel*` restricted to `bedrock_regions` (EU) — Claude on Bedrock EU for strict EU residency. |
| PostgreSQL | RDS PostgreSQL 16 (pgvector is available as an extension), Multi-AZ, KMS-encrypted storage, `rds.force_ssl`, 14-day backups, Performance Insights, deletion protection. |
| Redis | ElastiCache Redis 7.1, Multi-AZ with failover, TLS in transit, KMS at rest, AUTH token. |
| Object storage | S3 bucket (SSE-KMS, versioning, public access blocked, bucket-owner enforced). |
| Shared files | EFS (KMS) for the chart's ReadWriteMany volume (project repositories). |
| Keys | One customer-managed KMS key with rotation. |

## Usage

```bash
cd infra/terraform/aws
terraform init
terraform apply -var name=acme-messer -var region=eu-central-1
aws eks update-kubeconfig --name "$(terraform output -raw cluster_name)" --region "$(terraform output -raw region)"
terraform output -raw database_url   # owner connection for migrations
terraform output -raw redis_url
```

Then: create an EFS StorageClass with `fileSystemId = $(terraform output -raw efs_file_system_id)`, create the
`messer-data-plane` and `messer-data-plane-mtls` secrets, and install the chart with
`serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=$(terraform output -raw workload_role_arn)` and
`persistence.storageClass=<efs class>`. Enable the Anthropic models in the Bedrock console of the EU region(s)
you use. Store the Terraform state in an encrypted, versioned S3 backend in the same region.

Inputs: `name`, `region`, `bedrock_regions`, `vpc_cidr`, `availability_zones`, `kubernetes_version`,
`node_instance_types`, `node_min_size`/`node_max_size`/`node_desired_size`, `cluster_public_access_cidrs`,
`postgres_instance_class`, `postgres_allocated_storage_gb`, `postgres_multi_az`, `postgres_backup_retention_days`,
`redis_node_type`, `deletion_protection`, `kubernetes_namespace`, `kubernetes_service_account`, `tags`.

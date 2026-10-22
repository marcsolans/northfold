# Messer data plane — Google Cloud (EU)

Creates the infrastructure for the [`messer-data-plane`](../../helm/messer-data-plane) chart in **your** GCP
project, in a European region (`europe-west3` Frankfurt by default; non-`europe-*` regions are rejected):

| Resource | Details |
|---|---|
| Network | Custom VPC and subnet with pod/service ranges, Cloud NAT, private service access for Cloud SQL and Memorystore. |
| Kubernetes | Regional private GKE (Regular channel), workload identity, application-layer secrets encryption with Cloud KMS, Calico network policy, Filestore CSI driver (ReadWriteMany), shielded nodes. |
| Workload identity | Google service account bound to the chart's Kubernetes service account, with object admin on the bucket. |
| PostgreSQL | Cloud SQL for PostgreSQL 16 (pgvector extension available), private IP only, TLS only, regional HA, PITR, 14 backups, CMEK. |
| Redis | Memorystore Redis 7.2 Standard HA, AUTH, TLS (server authentication), CMEK. |
| Object storage | Cloud Storage bucket (uniform access, public access prevention, versioning, CMEK). |
| Keys | Cloud KMS key ring and key with 90-day rotation; service agents granted encrypt/decrypt. |

## Usage

```bash
cd infra/terraform/gcp
terraform init
terraform apply -var project_id=<project> -var name=acme-messer -var region=europe-west3
gcloud container clusters get-credentials "$(terraform output -raw cluster_name)" --region "$(terraform output -raw region)"
```

Install the chart with `serviceAccount.annotations."iam\.gke\.io/gcp-service-account"=$(terraform output -raw workload_service_account)`
and `persistence.storageClass=standard-rwx` (Filestore). Memorystore TLS uses a server CA: add it to the
trust store of the pods or download it with `gcloud redis instances describe … --format='value(serverCaCerts)'`.

**Models on GCP:** Claude through the Anthropic API (standard residency) or Amazon Bedrock in an EU region for strict
EU residency (AWS credentials in the chart secret).

# Messer data plane — Azure (EU)

Creates the infrastructure for the [`messer-data-plane`](../../helm/messer-data-plane) chart in **your** Azure
subscription, in a European region (`westeurope` by default; others are rejected by validation):

| Resource | Details |
|---|---|
| Network | VNet with subnets for AKS, PostgreSQL (delegated) and private endpoints; private DNS zones. |
| Kubernetes | AKS (Standard tier, 3 zones, autoscaling, Azure CNI + network policy), OIDC issuer and workload identity, Key Vault CSI driver, Azure Files/Blob CSI drivers (ReadWriteMany volume). |
| Workload identity | User-assigned identity federated with the chart's service account: Blob Data Contributor and Key Vault Secrets User. |
| PostgreSQL | Flexible Server 16, private (VNet-integrated), zone-redundant HA, `VECTOR`, `PG_TRGM` and `UNACCENT` allow-listed, TLS required, 14-day backups. |
| Redis | Azure Cache for Redis, TLS 1.2 only, public access disabled, private endpoint. |
| Object storage | Storage account (ZRS, TLS 1.2, no shared keys, no public access, private endpoint) encrypted with a customer-managed Key Vault key. |
| Keys | Key Vault Premium (RBAC, purge protection) with an HSM key and automatic rotation. |

## Usage

```bash
cd infra/terraform/azure
terraform init
terraform apply -var subscription_id=<id> -var name=acmemesser -var location=westeurope
az aks get-credentials -g "$(terraform output -raw resource_group)" -n "$(terraform output -raw cluster_name)"
```

Install the chart with `serviceAccount.annotations."azure\.workload\.identity/client-id"=$(terraform output -raw workload_client_id)`,
pod label `azure.workload.identity/use: "true"` (`podLabels`) and `persistence.storageClass=azurefile-csi-premium`.
After the first `make migrate`, run `CREATE EXTENSION vector; CREATE EXTENSION pg_trgm; CREATE EXTENSION unaccent;`
if your migration role cannot create extensions.

**Models on Azure:** Claude is reached through the Anthropic API (standard residency) or through Amazon Bedrock in an
EU region (strict EU residency: provide `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` in the chart secret).

# messer-data-plane (Helm chart)

Runs the Messer **data plane** — runtime, workers, scheduler, voice gateway and MCP server — in your own
Kubernetes cluster (customer cloud / BYOC or on-premise). Knowledge bases, traces, conversations, files and
project repositories stay in your account; only orchestration crosses to the Messer control plane over an
outbound mTLS connection. Architecture: [`docs/byoc.md`](../../../docs/byoc.md). Air-gapped installs:
[`docs/on-prem.md`](../../../docs/on-prem.md).

## Prerequisites

- Kubernetes ≥ 1.27 in an EU region, a ReadWriteMany storage class (EFS, Azure Files, Filestore, NFS).
- PostgreSQL 16 with `pgvector`, `pg_trgm` and `unaccent`; Redis 7 with TLS. The Terraform modules in
  [`infra/terraform`](../../terraform) create all of this for AWS, Azure and GCP.
- The environment registered with Messer (customer-cloud environment registration), which gives you the
  `dataPlaneId`, and mTLS material from [`infra/scripts/mtls-gen.sh`](../../scripts/mtls-gen.sh).

## Secrets (never in values)

```bash
kubectl create namespace messer
kubectl -n messer create secret generic messer-data-plane \
  --from-literal=DATABASE_URL='postgresql+psycopg://messer:…@db:5432/messer?sslmode=require' \
  --from-literal=DATABASE_APP_URL='postgresql+psycopg://messer_app:…@db:5432/messer?sslmode=require' \
  --from-literal=DATABASE_READONLY_URL='postgresql+psycopg://messer_readonly:…@db:5432/messer?sslmode=require' \
  --from-literal=REDIS_URL='rediss://:…@redis:6379/0' \
  --from-literal=MESSER_SECRETS_KEY="$(python -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')" \
  --from-literal=MESSER_JWT_SECRET="$(openssl rand -hex 32)" \
  --from-literal=MESSER_SERVICE_TOKEN='<service token issued by Messer for this environment>'
kubectl -n messer create secret generic messer-data-plane-mtls \
  --from-file=ca.crt=mtls/prod/ca.crt --from-file=tls.crt=mtls/prod/client.crt --from-file=tls.key=mtls/prod/client.key
```

Add the model provider you use: `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` (or workload identity) for Claude on
Bedrock EU — required for organizations in strict EU residency — or `ANTHROPIC_API_KEY`. External Secrets
Operator or the CSI secrets store can manage the same Secret names.

## Install

```bash
helm upgrade --install messer-dp infra/helm/messer-data-plane -n messer \
  --set controlPlane.url=https://api.messer.eu \
  --set controlPlane.dataPlaneId=<id> \
  --set persistence.storageClass=<rwx-class> \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=<workload_role_arn>
```

Run the database migrations once per release from the API image (`alembic -c infra/migrations/alembic.ini
upgrade head`) or let the control plane run them through the runtime when the environment is registered.

## Main values

| Key | Default | Purpose |
|---|---|---|
| `global.imageRegistry` / `global.imageTag` | `ghcr.io/messer` / appVersion | Image source (mirror it for air-gapped installs). |
| `controlPlane.url`, `controlPlane.dataPlaneId` | — | Outbound control-plane endpoint and environment id. |
| `mtls.enabled`, `mtls.existingSecret` | `true`, `messer-data-plane-mtls` | Client certificate mounted at `/etc/messer/mtls`. |
| `secrets.existingSecret` | `messer-data-plane` | Database, Redis, signing keys, provider keys. |
| `config.*` | EU defaults | Non-secret environment (`MESSER_EMBEDDINGS_PROVIDER=local`, `AWS_REGION=eu-central-1`…). |
| `components.<name>.*` | runtime, worker, scheduler, voice, mcp | Replicas, resources, HPA, PDB, probes, extra env. |
| `persistence.*` | RWX 100Gi | Project repositories and local file storage. |
| `networkPolicy.*` | enabled | Ingress only from the release and the ingress namespace; egress to DNS, PostgreSQL, Redis, HTTPS. Restrict with CIDRs. |
| `serviceMonitor.enabled` | `false` | Prometheus Operator scraping. |

Pods run as non-root with a read-only root filesystem, no capabilities and `RuntimeDefault` seccomp; `/tmp` and
`/cache` are `emptyDir` volumes.

## Validate

```bash
helm lint infra/helm/messer-data-plane --strict
helm template messer-dp infra/helm/messer-data-plane --set controlPlane.dataPlaneId=test | kubectl apply --dry-run=client -f -
```

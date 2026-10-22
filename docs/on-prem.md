# On-premise and air-gapped installation

On-premise installations run the **same data-plane images and Helm chart** as customer-cloud deployments
([`byoc.md`](byoc.md)). This guide covers clusters without direct internet access: private container registry,
offline models and the minimum connectivity Messer needs.

## 1. Requirements

| Component | Minimum |
|---|---|
| Kubernetes | 1.27+, 3 worker nodes (4 vCPU / 16 GiB each), a ReadWriteMany storage class (NFS, CephFS, Longhorn RWX…) |
| PostgreSQL | 16 with the `vector`, `pg_trgm` and `unaccent` extensions installed from your OS packages (`postgresql-16-pgvector`) |
| Redis | 7.x with TLS (`rediss://`) and a password |
| Object storage | The chart's RWX volume (`MESSER_STORAGE_DIR`) or any S3-compatible store reachable from the cluster |
| Workstation | `helm` 3.14+, `kubectl`, `skopeo` or `crane`, `openssl` |

## 2. Mirror the images into a private registry

On a machine with internet access, copy the images of the release you install (the chart `appVersion`):

```bash
VERSION=1.0.0
REGISTRY=registry.internal.example.com/messer
for image in messer-runtime messer-worker messer-scheduler messer-voice messer-mcp messer-api; do
  skopeo copy --all "docker://ghcr.io/messer/${image}:${VERSION}" "docker://${REGISTRY}/${image}:${VERSION}"
done
```

For a fully disconnected site, export to an archive and import it inside the perimeter:

```bash
for image in messer-runtime messer-worker messer-scheduler messer-voice messer-mcp messer-api; do
  skopeo copy "docker://ghcr.io/messer/${image}:${VERSION}" "oci-archive:${image}-${VERSION}.tar"
done
# … transfer the .tar files through your approved channel, verify their sha256, then:
for archive in *.tar; do
  name="${archive%-${VERSION}.tar}"
  skopeo copy "oci-archive:${archive}" "docker://${REGISTRY}/${name}:${VERSION}"
done
```

Also mirror the chart (`helm package infra/helm/messer-data-plane`) and, if you use them, the base images of your
PostgreSQL and Redis operators. Pin images by digest in production (`global.imageTag: "1.0.0@sha256:…"`).

## 3. Install

```bash
kubectl create namespace messer
kubectl -n messer create secret docker-registry registry-credentials \
  --docker-server=registry.internal.example.com --docker-username=… --docker-password=…
# secrets: see infra/helm/messer-data-plane/README.md (messer-data-plane and messer-data-plane-mtls)
helm upgrade --install messer-dp messer-data-plane-1.0.0.tgz -n messer \
  --set global.imageRegistry=registry.internal.example.com/messer \
  --set global.imagePullSecrets[0].name=registry-credentials \
  --set controlPlane.url=https://api.messer.eu \
  --set controlPlane.dataPlaneId=<id> \
  --set persistence.storageClass=<rwx-class>
```

Run the database migrations from the `messer-api` image once per release:

```bash
kubectl -n messer run messer-migrate --rm -it --restart=Never \
  --image=registry.internal.example.com/messer/messer-api:1.0.0 \
  --overrides='{"spec":{"containers":[{"name":"m","image":"registry.internal.example.com/messer/messer-api:1.0.0","envFrom":[{"secretRef":{"name":"messer-data-plane"}}],"command":["alembic","-c","infra/migrations/alembic.ini","upgrade","head"]}]}}'
```

## 4. Connectivity

| Destination | Needed for | Air-gapped alternative |
|---|---|---|
| Messer control plane (443, mTLS) | Orchestration: deployments, run commands, approvals | Allow-list only `controlPlane.url` through your egress proxy. A fully isolated site without control-plane connectivity runs with a self-hosted control plane (contact Messer). |
| Model provider (443) | Claude | Claude on Amazon Bedrock in an EU region through AWS PrivateLink (VPC endpoint `bedrock-runtime`) or an internal, OpenAI/Anthropic-compatible model gateway registered as a provider in `config/models.yaml`. |
| Embeddings | Knowledge search | Already offline: `MESSER_EMBEDDINGS_PROVIDER=local` runs the multilingual model inside the worker image. |
| Email | Notifications | Your internal SMTP relay (`MESSER_EMAIL_PROVIDER=smtp`, `SMTP_HOST`…). |
| Channels and voice | WhatsApp, Telegram, phone | Disable the components you do not use (`components.voice.enabled=false`); browser voice works inside the network. |

Set the chart's `networkPolicy.egress.httpsCidrs` to the proxy or endpoint addresses so pods cannot reach anything
else.

## 5. Offline models

* **Embeddings**: the local multilingual model ships in the worker and runtime images (`fastembed` cache under
  `/cache`). To pre-seed a custom model, build a derived image that copies it into the cache directory and set
  `MESSER_EMBEDDINGS_PROVIDER=local`.
* **Chat models**: point the model gateway at your private endpoint (Bedrock EU via PrivateLink, or a self-hosted
  model behind an Anthropic-compatible API) and list it in `packages/messer-common/src/messer_common/config/models.yaml`
  (tiers *Fast*, *Standard*, *Powerful*). Model ids are configuration, never code.
* Organizations with **strict EU residency** only accept Bedrock in an EU region and local embeddings; the policy is
  enforced by `messer_common.residency.allowed_provider`.

## 6. Updates and verification

1. Mirror the new images (step 2) and verify digests.
2. Run the migrations of the new release.
3. `helm upgrade` with the new `global.imageTag`; components roll one replica at a time (PDBs keep one available).
4. Check `kubectl -n messer get pods`, each service's `/health`, and the environment status in Messer.

Backups (PostgreSQL PITR, RWX volume snapshots), monitoring (`serviceMonitor.enabled=true` with Prometheus Operator)
and retention (scheduler, per organization) behave exactly as in the customer-cloud deployment.

# Runbook — Messer operations

Who this is for: whoever is on call for the Messer cloud (EU). Every service exposes `GET /health`; the scheduler
checks them every minute, updates the public status page (`/status`) and emails `MESSER_OPS_EMAIL` on down and on
recovery.

## Services at a glance

| Service | What it does | Health | Scale |
|---|---|---|---|
| `web` (Next.js, Vercel `fra1`) | Website, Studio, public chat/apps, same-origin `/api` rewrite | `/health` | Stateless |
| `api` (FastAPI, Railway EU) | Control plane: auth, projects, billing, approvals, deployments, webhooks | `/health` (DB + Redis) | Stateless, ≥ 2 replicas |
| `runtime` (Railway EU / BYOC) | Sandboxes, model gateway, tracing backend | `/health` | One sandbox per (project, commit); scale replicas, sticky by project if possible |
| `worker` (arq) | Ingestion, syncs, evals, deploys, triggers, approvals, exports | Redis heartbeat `messer:heartbeat:worker` | Horizontal |
| `scheduler` | Cron triggers, approval expiry, alarms, billing lifecycle, retention, health checks | Leader key `messer:scheduler:leader` | 2 instances (one leader) |
| `voice`, `mcp` | Voice gateway, MCP server | `/health` | Horizontal |
| Postgres 16 + pgvector (Supabase EU) | All data, RLS | `pg_isready` | Managed |
| Redis | Queue, events, caches, rate limits | `redis-cli ping` | Managed |

## First five minutes of any incident

1. Open `/status` (fed by the `service_health` table) to see which component is down.
2. Check the last deploy (Railway/Vercel). If the incident started right after it, **roll back** first, investigate later.
3. Sentry (EU) for new errors; API logs are JSON (`structlog`) with `request_id`.
4. Incidents on `/status` are derived automatically from health transitions; tell affected enterprise customers
   directly and record the timeline for the post-mortem.

## Playbooks

### API returns 5xx
- `GET /health` reports which dependency fails (`database`, `redis`).
- Database unreachable: check Supabase status; connections exhausted → look for long transactions
  (`select pid, now()-xact_start, query from pg_stat_activity order by 2 desc`), terminate offenders.
- Redis down: the API stays up (rate limits fail open, events degrade), but jobs are not enqueued. Restore Redis;
  the scheduler re-sweeps cron triggers and approvals; idempotency keys prevent duplicates.

### Runs fail or hang
- Runtime `/health` and `/internal/v1/sandboxes` (service token) list sandboxes per project/commit.
- A project stuck in a crash loop: the runtime log shows `sandbox.stderr` lines with the traceback from project code;
  the customer sees the error in the trace. Nothing to do on our side unless it is platform code.
- Model provider outage: the gateway fails over Anthropic ↔ Bedrock automatically (EU-strict orgs only use Bedrock);
  if both are down, runs end with `overloaded_error`. Check `run:*:calls` in Redis or spans for the provider used.
- `budget_exceeded` / `credits_exhausted` are expected refusals (customer budgets); support can grant credits in
  `/admin` → Organizaciones → detalle → créditos (always with a note, audited).

### Webhooks (Stripe, channels, GitHub, triggers)
- Stripe: events are idempotent per event id (`stripe_events`); replay from the Stripe dashboard after fixing.
- Triggers/channels: firings are worker jobs keyed by event id; a provider retry never runs twice.

### Worker backlog
- Queue length: `redis-cli zcard arq:queue`. Scale the worker; long jobs (ingestion, evals) have a 30-minute timeout.
- Jobs retry with backoff on `RuntimeUnavailable`.

### Deployments blocked
- The evals gate failed: deployment logs show which member failed. Only an org admin can force; it is audited.
- Roll back from Proyecto → Despliegues → "Volver a esta versión" (skips evals; the version already passed them).

## Backups and restore

- Managed: Supabase daily backups + PITR (enable in the project; EU region).
- Application backups (database incl. knowledge-base schemas and roles, project git repositories, file storage):
  `infra/scripts/backup.sh /backups` (set `BACKUP_PASSPHRASE` to encrypt, `BACKUP_S3_URI` to upload). Schedule it
  daily (Railway cron or a Kubernetes CronJob in BYOC) and keep 30 days.
- Restore: stop api/runtime/worker/scheduler, then `infra/scripts/restore.sh /backups/messer-<stamp>`; it verifies
  checksums, recreates roles and memberships, replaces the database, restores repositories and storage and runs
  migrations. The procedure is exercised by `tests/ops/test_backup_restore.py` in CI (backup → wipe → restore).
- Knowledge-base backups for a single KB are available to customers in the KB page (worker `kb_backup` / `kb_restore`).

## Secrets and rotation

- Secrets live in the provider's secret manager (Railway/Vercel/Kubernetes secrets), never in the repository.
- `MESSER_SERVICE_TOKEN`: rotate by deploying the new value to api, runtime, worker and scheduler together.
- `MESSER_JWT_SECRET`: rotation signs everyone out (refresh tokens are hashed and remain valid only with the same
  secret for access tokens) — schedule it.
- `MESSER_SECRETS_KEY` encrypts connection credentials and project secrets (Fernet). Rotation requires re-encrypting:
  add the new key, run a one-off re-encryption job, remove the old key.
- Customer-facing API keys are revocable in Settings → API keys; leaked keys are revoked by admins at once.

## Security incidents

1. Contain: revoke keys/sessions (`/admin` → Usuarios → bloquear revokes sessions), rotate affected secrets.
2. Preserve evidence: the audit log is insert-only; export it (`/api/v1/audit-log/export.csv`).
3. GDPR: notify the supervisory authority within 72 h when personal data is affected; the DPO contact is in the
   legal pages.

## Routine tasks

- Impersonation for support: `/admin` → Organizaciones → detalle → impersonar (max 2 h, banner visible, audited).
- Data requests (export / erasure): customers from Ajustes → Datos; operators via `GET/POST /api/v1/admin/data-requests`.
- Model prices: `/admin` → Precios de modelos (affects credits immediately; the runtime caches prices for 60 s).
- Feature flags: `/admin` → Flags.

# CLAUDE.md — Messer

Messer is an enterprise platform to build, run and govern AI solutions (agents, workflows, knowledge,
interfaces). Spanish-first UI (English second), EU infrastructure, everything exportable as code.
Read `PROGRESS.md` (what is done / pending) and `DECISIONS.md` (why) before changing anything.

## Layout

```
apps/api            FastAPI control plane (package messer_api). Routers auto-discovered from routers/*.py:
                    `router` → /api/v1, `public_router` → root (public API, hooks, webhooks).
apps/web            Next.js 16 app: marketing site, auth, Studio (/app), backoffice (/admin), public chat.
services/runtime    Data plane: runs project agents/workflows in sandboxed subprocesses (messer_runtime).
services/worker     arq jobs: ingestion, syncs, composer builders, evals, deploys, triggers (messer_worker).
services/scheduler  Cron triggers, source watching, expiries, alarms (messer_scheduler).
services/voice      Voice gateway (messer_voice).    services/mcp   Messer MCP server (messer_mcp).
packages/messer-core   Engine (renamed fork, import `messer`): Agent, Workflow, Tool, events, approvals,
                       guardrails, evals, voice, HTTP server. Has its own CLAUDE.md and test suite.
packages/messer-common Shared kernel: settings, ORM models (db/models/*), RLS sessions, security, pricing,
                       models.yaml, email/storage/queue/events adapters, pytest fixtures (testing/).
packages/connectors    Connector catalog + adapters.     packages/templates  Industry project templates.
packages/ui            React design system + interface components (@messer/ui).
packages/messer-sdk-ts / messer-sdk-py   SDKs generated from OpenAPI.
infra/migrations    Alembic (owner connection).  infra/helm, infra/terraform  BYOC data plane.
tests/e2e           Playwright journeys (reads emails from Mailpit).
```

## Commands

- Install: `uv sync --all-packages && pnpm install`
- Local services (no Docker here): Postgres 16 + pgvector and Redis run natively; Mailpit: `~/go/bin/mailpit`.
  The session environment exports a placeholder `DATABASE_URL`; prefix Python commands with `env -u DATABASE_URL`
  so the values in `.env` are used.
- Migrate + seed: `make bootstrap` · API: `make api` (:8000, docs at /api/docs) · Web: `make web` (:3000)
- Tests: `make test-core` (engine, ~3 min with -n 4) · `make test-api` (platform; real Postgres db `messer_test`)
  · `pnpm --filter @messer/e2e test` with `PLAYWRIGHT_CHROMIUM_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome`
- Lint/types: `make lint`, `make typecheck` (ruff, pyright, eslint, tsc)

## Conventions

- Code, identifiers, commits: English. UI copy: Spanish first, English in `apps/web/messages/en/<ns>.json`.
  Each area owns one namespace file per locale; never put user-facing text in components.
- Every business table has `org_id` and RLS. User requests use `Depends(get_db)` (RLS session on `messer_app`);
  system work uses `system_session()` and must filter by `org_id`. Register RLS with `rls(table, read=, write=)`
  in the model module and add a migration for new tables/policies.
- Roles: `require_role("viewer"|"builder"|"admin"|"owner")`; builder+ also enforces billing read-only state.
- Errors: raise `ApiError` subclasses (`NotFound`, `Forbidden`, `PlanLimitExceeded`, …) → `{"error": {code, message, details}}`.
- Mutations that matter call `messer_common.audit.record(...)` in the same transaction.
- Secrets: never in code. Encrypt at rest with `messer_common.security.encrypt/encrypt_json`; API keys/tokens stored
  as `hash_token`. Model ids only in `config/models.yaml`.
- No mock data in the UI. Missing keys → real adapter in demo/test mode, flagged in `/api/v1/system/status` and
  PROGRESS.md "Pending keys".
- Web: client components fetch with TanStack Query via `lib/api.ts` (`http.get/post/...`), SSE via `lib/sse.ts`.
  Every list page has loading (Skeleton), empty (EmptyState) and error (ErrorState) states; destructive actions use
  `ConfirmDialog`.

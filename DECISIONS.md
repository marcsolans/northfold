# Decisions

Technical decisions not fixed by the specification. Simplest option that satisfies the principles.
Format: **D-NNN — title.** Decision. *Why.*

## Foundations

**D-001 — Engine fork placement.** The complete upstream engine repository (Python framework, Zig CLI, Rust TUI, docs, examples, benchmarks, scripts) is copied into `packages/messer-core/` as one unit. The upstream project, tag (`v2.7.39`) and exact commit (`45f3298899f32f861f8573c918ae22bdf90e489f`) are recorded in `NOTICE` and `LICENSE_REVIEW.md` (the brand name may appear only in those files). *Keeping the tree intact makes future upstream syncs a mechanical rename + diff.*

**D-002 — Package names.** Engine distribution `messer-core`, import name `messer` (`from messer import Agent, Workflow`). Platform packages: `messer_common` (shared kernel), `messer_api` (control plane), `messer_runtime`, `messer_worker`, `messer_scheduler`, `messer_voice`, `messer_mcp`, `messer_connectors`, `messer_sdk`.

**D-003 — Engine dependency pins.** The root `pyproject.toml` pins every package in the upstream lock file through `[tool.uv] constraint-dependencies`. Resolving freely pulled `anthropic` 1.x and `openai` 3.x, which broke 68 engine tests (collector usage accounting). Platform-only dependencies resolve freely. *The engine test suite (5,352 tests) must stay green after the rename.*

**D-004 — Engine platform hooks redirected to Messer.** The engine's "platform" HTTP calls now target the Messer API: `orgs/{org}/apps/{app}/runs/{run}` → `orgs/{org}/projects/{project}/runs/{run}`; `orgs/{org}/k2/{kb}/query` → `orgs/{org}/knowledge-bases/{kb}/query`; `orgs/{org}/integrations/{id}` → `orgs/{org}/connections/{id}/credentials`. `MESSER_API_HOST` may be a full base URL (`http://runtime:8100/internal/v1`), defaulting to `${MESSER_API_URL}/api/v1`. Deployed environments resolve through the runtime (`${MESSER_RUNTIME_URL}/envs/{env_id}`). All upstream hostnames were rewritten to the non-routable `*.messer.local` so no default ever reaches a third party.

**D-005 — Extra shared package.** `packages/messer-common` holds settings, ORM models, sessions/RLS, crypto, pricing, model config, email/storage/queue/event adapters and test fixtures. It is used by the API (control plane) and by the runtime/worker (data plane), which keeps the runtime free of any dependency on control-plane code.

**D-006 — One migrations path: Alembic.** `infra/migrations` (owner connection). Supabase migrations are not used.

**D-007 — Row Level Security model.** Three Postgres roles: `messer` (owner; migrations and *system* work such as webhooks and schedulers, always filtering by `org_id` explicitly), `messer_app` (NOBYPASSRLS; every user request), `messer_readonly` (SQL console and agent SQL, switched per query to a per-knowledge-base reader role). Each request runs in a transaction that sets `app.user_id`, `app.org_id`, `app.superadmin` with `set_config(..., true)`; policies call `messer.has_role(org_id, min_role)` (SECURITY DEFINER over `memberships`). Every business table has `org_id`; policies are generated from a registry in the models and frozen into each migration. `audit_log` is insert-only (UPDATE/DELETE revoked). Auth internals have RLS enabled with no policy (invisible to the app role).

**D-008 — Authentication.** Default local backend: Argon2id passwords, rotating refresh-token sessions (only hashes stored), HS256 access JWTs with Supabase-compatible claims (`sub`, `email`, `aud=authenticated`, `aal`). When `SUPABASE_URL`/`SUPABASE_ANON_KEY` are set, credentials are delegated to Supabase Auth (GoTrue) and its tokens go into the same cookies; user ids equal the Supabase uid. MFA (TOTP + recovery codes) is enforced by Messer in both modes. Social login without Supabase uses OAuth 2.0 code + PKCE directly against Google/Microsoft.

**D-009 — Same-origin API.** The browser calls `/api/v1/*` on the web origin; Next.js rewrites to the API service. Cookies (`messer_at`, `messer_rt`, `messer_org`) are httpOnly/SameSite=Lax on the web domain, so Vercel ↔ Railway needs no cross-site cookies or permissive CORS.

**D-010 — Frontend toolchain.** Next.js 16 (App Router, `proxy.ts`), React 19, TypeScript 6.0 (the native TypeScript 7 compiler is not yet a safe default for Next), Tailwind CSS 4, Radix primitives with shadcn-style components written in `packages/ui` (the shadcn registry is not fetched at build time), Geist fonts from npm (no Google Fonts request at build or run time).

**D-011 — Internationalisation.** next-intl without locale URL prefixes. Spanish is the default for everyone; English is opt-in (language switcher, profile, or `?lang=en`) and persisted in `NEXT_LOCALE`. Messages are split per namespace (`messages/<locale>/<namespace>.json`) so each area owns its file.

**D-012 — Content Security Policy.** Nonce-based strict CSP (`'strict-dynamic'`) set per request in `proxy.ts`; Monaco is served from `/monaco/vs` (copied from npm at install) instead of a CDN. `/embed/*` pages may be framed (embeddable chat); everything else sends `frame-ancestors 'none'`.

**D-013 — Model configuration.** `packages/messer-common/src/messer_common/config/models.yaml` holds tiers (Fast = `anthropic/claude-haiku-5-5`, Standard = `anthropic/claude-sonnet-5-5`, Powerful = `anthropic/claude-opus-5-5`), Guard small/large models, Composer roles, Bedrock EU model ids (`anthropic.<id>`, Mantle client, `eu-central-1`) and seed prices for `model_prices`. Haiku 5.5 cache read/write prices are derived (0.1× / 1.25× input) because the cached models table publishes input/output only; they are editable in /admin.

**D-014 — Logo.** A red square (`#D52B1E`) with a white diagonal blade and the wordmark. The Swiss cross was avoided: it is a protected national emblem.

**D-015 — Test isolation.** Python tests use a real Postgres database (`$MESSER_TEST_DATABASE`, default `messer_test`) migrated once per session and truncated after each test, and Redis db 15. Parallel workstreams use different database names.

**D-016 — Email locally.** SMTP to Mailpit (`:1025`, UI `:8025`). In `local`/`test`, if SMTP is unreachable the email is logged to the console instead of failing the request. E2E tests read emails through the Mailpit API.

**D-017 — Docker in the build environment.** The build sandbox has no Docker daemon, so `docker compose up` cannot be executed here; compose files are validated with `docker compose config` and every service is also runnable natively (`make api`, `make web`, …). CI runs the same services natively.

# Progress

## Phase status

| Phase | Status |
|---|---|
| 1. Foundations | ✅ Closed |
| 2. Business | ✅ Closed |
| 3. Runtime and Agent builder | ✅ Closed |
| 4. Knowledge and connectors | ✅ Closed |
| 5. Workflows, triggers and approvals | 🔧 In progress (triggers, approvals inbox and email done; workflow builder in progress) |
| 6. Composer | ⏳ |
| 7. Interfaces, deployment and governance | 🔧 In progress (deployments, domains, GitHub sync, export done; interfaces and analytics in progress) |
| 8. Channels and voice | 🔧 In progress |
| 9. Templates | ⏳ |
| 10. Developers | ⏳ |
| 11. Enterprise | ✅ Closed |
| 12. Guard | 🔧 In progress (gateway extension point done) |
| 13. Final hardening | ⏳ |

## Phase 1 — Foundations (closed)

Done:
- Monorepo (uv workspace + pnpm workspace), `.env.example`, Makefile, docker-compose (Postgres+pgvector, Redis,
  Mailpit, migrate+bootstrap, api, web), Dockerfiles for api and web, CI (lint, types, engine + platform tests,
  build, Playwright e2e, pip-audit, npm audit, gitleaks) and deploy workflow (Railway + Vercel, token-gated).
- Engine fork copied whole into `packages/messer-core`, renamed (packages, imports, env vars `MESSER_*`, config
  `messer.yaml`, text, docs, TUI, CLI), platform calls redirected to the Messer API, logos replaced, NOTICE and
  LICENSE_REVIEW written. **Engine test suite after rename: 5,352 passed, 0 failed.**
- Database schema for every table in the spec (54 tables) + RLS migration: roles, policy helpers, 168 policies,
  insert-only audit log, Spanish/English full-text, `kb_vector_search` / `kb_text_search` / `kb_hybrid_search` (RRF).
- Auth: local (Argon2id, rotating refresh sessions, JWT) or Supabase; Google/Microsoft OAuth (PKCE); MFA (TOTP +
  recovery codes); password reset; email verification; rate limits on login/sign-up.
- Organizations (create, switch, update), memberships with roles owner/admin/builder/viewer (API + RLS), invitations
  by email (single-use token, 7 days), audit log API with CSV export, notifications API.
- Web: design system (`@messer/ui`), i18n (es/en), strict CSP with nonces, cookie consent (PostHog only after
  acceptance), auth pages, app shell (sidebar, org switcher, ⌘K palette, notifications, theme, language), members
  and profile/MFA settings. Sentry on API and web (inactive without DSN).
- Tests: API auth/org/invitation/MFA/reset (7) + RLS isolation across every business table (5); Playwright:
  sign up → invite viewer by email (Mailpit) → viewer joins with read-only rights.

Pending (later phases): remaining services and screens per phase plan.

## Phase 2 — Business (closed)

Done:
- Plans (Starter €49, Pro €199, Business €799, Enterprise from €3,000; annual prices), credit packs, plan limits
  (`services/limits.py`), 14-day Pro trial with credits, trial emails (day 1/3/7/12), dunning (grace period →
  read-only), budgets per organization and project with alerts and hard stop, AI credits ledger with idempotent
  usage charges and automatic top-up (D-026).
- Stripe (Checkout, portal, Tax, webhooks state machine) **or** simulated test mode with the same flows.
- Public website: landing with Composer animation, pricing from the live plans API, security, templates, contact,
  status page, blog with RSS, docs, six legal documents (drafts pending a lawyer: company name, tax id, address, DPO,
  jurisdiction placeholders), SEO (sitemap, robots, hreflang, OG, JSON-LD offers).
- Onboarding (4 skippable steps from real data) and activation checklist.
- Backoffice `/admin`: organizations, users, impersonation (audited, 2 h max), plans and Stripe sync, model prices,
  templates, feature flags, MRR and usage metrics.
- Verified by: pytest business suite (49) + website (23) and Playwright `02-website` (landing → pricing → sign-up
  from a plan → onboarding); business acceptance test (sign up → Pro in test mode → MRR in /admin).

## Phase 3 — Runtime and Agent builder (closed)

Done:
- `services/runtime`: sandbox per (project, commit) with scrubbed env and rlimits (D-021), code at exact commits,
  engine platform API (tracing, files, tool proxy, knowledge, connector actions), run orchestration with spans, cost,
  credits and approvals (D-018, D-022).
- Model gateway: residency routing (EU strict → Bedrock only), failover, model policy, credits/budget checks on
  every call, per-call cost; offline demo model when no key (D-019, D-020); Guard extension point.
- Agent builder: config ↔ `agent.py` two-way sync (code wins otherwise), tools catalog with "requires approval" and
  approver role on any tool, connector actions, MCP servers, knowledge bases, context files, guardrails (shadow /
  enforce), memory, Monaco code editor, versions with diff/restore, evals; playground chat (streaming, tool cards,
  inline approval cards incl. approve-with-changes, attachments, conversations, trace links).
- Runs/traces API + UI (waterfall, per-span tokens/cost, re-run on the same commit, feedback), approvals inbox and
  email links that never decide on GET (D-023), public run API with API keys (D-025), API keys and project secrets.
- Verified by: pytest (runtime 15, studio/runs 5, deployments/triggers 9, keys/secrets 2) and Playwright
  `03-studio` (agent created in the UI → chat → approval pauses → approve → resumes → trace with cost and credits).
  Real-provider cost and credit deduction are verified with a mocked Anthropic transport (no key in this
  environment); in demo mode runs cost 0.

## Phase 4 — Knowledge and connectors (closed)

Done:
- Knowledge bases with their own schema, reader role and policies; ingestion of PDF, DOCX, PPTX, XLSX/CSV, HTML,
  Markdown/TXT and EML with structure-aware chunking; embeddings (local multilingual model, Voyage, Bedrock, offline
  hash); vector, keyword and hybrid (RRF) search; tables from CSV/Excel or syncs with column types; read-only SQL
  console with `embed()` and policies; entities; KB backups; live ingestion status (D-028).
- 17 connectors: Google Drive, Gmail, Google Calendar, OneDrive, SharePoint, Outlook, Slack, Notion, HubSpot,
  Salesforce (OAuth 2), PostgreSQL, MySQL, SQL Server (read-only, schema introspection, incremental table syncs),
  webhooks (HMAC), generic HTTP, MCP servers, on-prem files; demo mode runs each adapter against an in-process fake
  of the provider API; syncs into knowledge bases; connector events for workflow triggers; on-prem connector agent
  (outbound WebSocket, enrollment, PyInstaller spec) (D-033).
- Verified by: knowledge suite (74), connectors suite (118) and the acceptance test
  `apps/api/tests/knowledge/test_phase4_acceptance.py` — 3 PDFs + a CSV uploaded, a Drive folder synced in demo
  mode, an agent answers through the runtime citing `condiciones-generales.pdf`, and a SQL query joins the invoices
  table with the documents view.

## Phase 11 — Enterprise (closed)

Done:
- SSO: OIDC (PKCE, JWKS validation) and SAML (signed assertions, replay protection), presets for Entra ID, Google
  Workspace and Okta, group → role mapping, JIT provisioning, "enforce SSO"; verified email domains (D-029).
- SCIM 2.0 (`/scim/v2`) users and groups with deprovisioning; MFA from phase 1.
- Strict EU residency (Bedrock EU only, tested in the runtime), retention policies (scheduler), GDPR export and
  erasure jobs for users and organizations, legal documents.
- BYOC: Helm chart (lint/template pass) and Terraform for AWS, Azure and GCP (fmt/validate pass), mTLS script,
  `docs/byoc.md`, `docs/on-prem.md`.
- Verified by: pytest enterprise suite (72) — fake OIDC IdP and signed SAML login, SCIM flows, GDPR export/delete —
  and the runtime test "EU strict uses Bedrock only".

## Pending keys

Missing keys run in demo/sandbox mode. To enable each integration, set the variables in `.env` (local) or in the
provider's secret manager (Railway/Vercel) and restart the services.

| Variable(s) | Feature | How to enable |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude models (currently the deterministic demo model) | Create a key at console.anthropic.com → set it in the API, runtime and worker services. |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `DATABASE_URL` | Supabase Auth + Storage + Postgres (EU) | Create a project in an EU region, enable pgvector, copy the API settings; point `DATABASE_URL` (owner) at it and run `make bootstrap`. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY` | Real Stripe billing (simulated test mode now) | Test-mode keys from the Stripe dashboard; add a webhook to `/api/v1/webhooks/stripe`. |
| `POSTMARK_SERVER_TOKEN` or `RESEND_API_KEY` | Transactional email in production | Set `MESSER_EMAIL_PROVIDER=postmark|resend` and verify the sending domain. |
| `SENTRY_DSN`, `NEXT_PUBLIC_SENTRY_DSN` | Error monitoring (EU) | Create a Sentry project in the EU region (`*.ingest.de.sentry.io`). |
| `NEXT_PUBLIC_POSTHOG_KEY` | Product analytics (EU) | PostHog EU project key. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | Claude on Bedrock EU for `eu_strict` orgs | IAM user with `bedrock:InvokeModel*` in an EU region; enable Anthropic models in the Bedrock console. |
| `GOOGLE_CLIENT_ID/SECRET`, `MICROSOFT_CLIENT_ID/SECRET` | Social login and connectors | OAuth apps with redirects `https://<web>/api/v1/auth/oauth/<provider>/callback` (login) and `https://<web>/api/v1/connections/oauth/<connector>/callback` (connectors). |
| `SLACK_CLIENT_ID/SECRET`, `NOTION_CLIENT_ID/SECRET`, `HUBSPOT_CLIENT_ID/SECRET`, `SALESFORCE_CLIENT_ID/SECRET` | Real connections to those providers (demo fakes otherwise) | Create an OAuth app per provider with redirect `https://<web>/api/v1/connections/oauth/<connector>/callback`. |
| `RAILWAY_TOKEN`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` (GitHub secrets) | Auto-deploy staging/production | Connect the repo in Railway (EU) and Vercel (functions in `fra1`), add tokens as repository secrets. |
| `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET` | Project sync via GitHub App (personal-token mode works without them) | Create a GitHub App (contents read/write, push webhook to `/api/github/webhook`). |
| `MESSER_INBOUND_EMAIL_SECRET` (+ inbound provider) | Email triggers and email channel from real mailboxes (simulate endpoint works without it) | Configure Postmark inbound (or similar) for `MESSER_INBOUND_EMAIL_DOMAIN` with webhook `/api/inbound/email?token=…`. |
| `SUPABASE_SERVICE_ROLE_KEY` | Deleting the Supabase auth user during GDPR erasure (Supabase mode only) | From the Supabase project API settings. |
| `VOYAGE_API_KEY` (optional) | Hosted embeddings (the local multilingual model is used otherwise) | Voyage AI dashboard. |
| `MESSER_SALES_EMAIL`, `MESSER_OPS_EMAIL` | Contact form and service alerts recipients (fall back to the superadmin email) | Set the team addresses. |
| `HAWK_API_KEY` | StackHawk DAST scan of the running app (security review) | StackHawk account API key. |

## Blockers

- The build environment has no Docker daemon: `docker compose up` is validated with `docker compose config` and all
  services are exercised natively (same commands as CI). See D-017.

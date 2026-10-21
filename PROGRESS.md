# Progress

## Phase status

| Phase | Status |
|---|---|
| 1. Foundations | ✅ Closed |
| 2. Business | ⏳ |
| 3. Runtime and Agent builder | ⏳ |
| 4. Knowledge and connectors | ⏳ |
| 5. Workflows, triggers and approvals | ⏳ |
| 6. Composer | ⏳ |
| 7. Interfaces, deployment and governance | ⏳ |
| 8. Channels and voice | ⏳ |
| 9. Templates | ⏳ |
| 10. Developers | ⏳ |
| 11. Enterprise | ⏳ |
| 12. Guard | ⏳ |
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
| `GOOGLE_CLIENT_ID/SECRET`, `MICROSOFT_CLIENT_ID/SECRET` | Social login and connectors | OAuth apps with redirect `https://<web>/api/v1/auth/oauth/<provider>/callback`. |
| `RAILWAY_TOKEN`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` (GitHub secrets) | Auto-deploy staging/production | Connect the repo in Railway (EU) and Vercel (functions in `fra1`), add tokens as repository secrets. |

## Blockers

- The build environment has no Docker daemon: `docker compose up` is validated with `docker compose config` and all
  services are exercised natively (same commands as CI). See D-017.

# Decisions

One line per decision: **decision** — reason.

- **Local PostgreSQL 16 for development, integration tests and CI; Neon only in deployed environments** — no `DATABASE_URL`/`DIRECT_URL` were provided and `neon.tech` is not reachable from the build VM.
- **TypeScript 6.0 (not 7.0)** — TS 7 (native port) is not yet supported by typescript-eslint (`<6.1.0`), which type-aware linting needs.
- **ESLint 10 with pnpm `peerDependencyRules` for three eslint-config-next plugins** — ESLint 9 is end-of-life; Next.js documents ESLint 10 support, only the plugins' peer ranges lag.
- **Prisma 7.10 (not 8.0)** — npm `latest` for `prisma` is an 8.0 release candidate; Better Auth's adapter supports Prisma ≤ 7.
- **Cache Components on (create-next-app default)** — catalog reads use `"use cache"` + tags, per-request UI streams in `<Suspense>`; no `export const dynamic` (it is not allowed with Cache Components).
- **Static CSP with `'unsafe-inline'` scripts instead of nonces** — nonce CSP forces every page to render dynamically, which disables Partial Prerendering.
- **Integrations (Stripe, Google, Cloudinary) are optional in `src/env.ts`, validated all-or-nothing** — the store runs locally with only Postgres; the UI hides a payment/sign-in/upload option that is not configured.
- **Vitest config is `.mts`** — the package is CommonJS (Next.js default) and Vite's native config loader warns about ESM in `.ts`.
- **GitHub Actions pinned to major tags (`checkout@v5`, `setup-node@v5`, `pnpm/action-setup@v4`, `upload-artifact@v4`)** — release pages are not reachable from the build VM to confirm newer majors; these are known-good.
- **Free shipping applies at subtotal ≥ $100** — "free over $100" is treated as inclusive, the customer-friendly reading.

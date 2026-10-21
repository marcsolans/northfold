# Northfold — Build Plan

Each phase ends with the phase gate: `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
(zero errors, zero warnings), a UI check at 375px and 1440px for every new page, and a
Conventional Commit.

## Phase 0 — Setup

- [x] Scaffold Next.js 16 (App Router, `src/`, TypeScript strict + `noUncheckedIndexedAccess`)
- [x] ESLint (flat config), Prettier (+ Tailwind plugin), Husky + lint-staged
- [x] Tailwind v4 design tokens in `@theme`, Poppins via `next/font`
- [x] `src/env.ts` (Zod-validated env, fail fast) and `.env.example`
- [x] `CLAUDE.md`, `docs/PLAN.md`, `docs/DECISIONS.md`
- [x] Vitest (unit + integration projects) and Playwright configured
- [x] GitHub Actions CI workflow

## Phase 1 — Database

- [x] Prisma 7 + driver adapters (Neon in production, `pg` locally)
- [x] Full schema (enums, models, indexes, snake_case `@@map`)
- [x] First migration committed (+ `stock >= 0` CHECK constraint)
- [x] `src/lib/money.ts` decimal-safe helper + tests
- [x] Idempotent seed script (`pnpm db:seed`): ~24 products, images, variants, admins

## Phase 2 — Auth

- [x] Better Auth (email/password + Google) with Prisma adapter
- [x] `role` not accepted as input
- [x] Sign-in / sign-up pages (React Hook Form + Zod)
- [x] `requireUser()` / `requireAdmin()` helpers
- [x] `proxy.ts` optimistic redirects
- [x] Rate limiting on sign-in / sign-up

## Phase 3 — UI kit + layouts

- [x] Primitives: Button, Input, Select, Badge, Card, Modal, Table, Skeleton, EmptyState
- [x] Storefront layout: navbar (search, account, cart badge, accessible mobile menu), footer
- [x] Admin layout with sidebar (no storefront navbar)

## Phase 4 — Catalog

- [x] Home: hero, featured, bestsellers, shop by category
- [x] Shop: URL-driven filters, search, sort, pagination, empty state, skeletons
- [x] Product page: gallery, variant selectors, quantity cap, related products, `generateMetadata`
- [x] `sitemap.ts`, `robots.ts`, Open Graph

## Phase 5 — Cart

- [x] Zustand store with `persist` + `skipHydration`
- [x] Cart page with totals (shipping threshold, tax constant)
- [x] Server revalidation of the cart (archived, stock clamp, price refresh) with change notices

## Phase 6 — Checkout + COD

- [ ] Checkout requires sign-in (redirect back)
- [ ] Address selection / new address (+ save), Zod on client and server
- [ ] `placeOrder` server action (server-side pricing, COD transaction with conditional stock decrement)
- [ ] Rate limit on `placeOrder`
- [ ] Success page reading the real order state

## Phase 7 — Stripe

- [ ] Checkout Session creation (cents at the boundary, 30 min expiry)
- [ ] Webhook: signature check, idempotency via `StripeEvent`, paid / expired handling, oversell flag
- [ ] Success page polling while the webhook is pending
- [ ] Integration tests with signed test payloads

## Phase 8 — Customer account

- [ ] Profile (name, change password for credential accounts)
- [ ] Addresses CRUD + default
- [ ] Order history (paginated) + detail with status timeline
- [ ] Cancel COD order while PENDING (restock in the same transaction)

## Phase 9 — Admin

- [ ] Overview: revenue (today / 30d / all), orders by status, customers, low stock, recent orders, chart
- [ ] Products: table, search, create/edit (RHF + Zod), images (upload, preview, reorder, remove), variants editor, archive vs delete
- [ ] Orders: filters, detail, status changes via state machine (restock on cancel)
- [ ] Customers: order count + total spent
- [ ] `requireAdmin()` inside every admin action, proven by tests

## Phase 10 — Hardening

- [ ] Security headers + CSP
- [ ] Accessibility + Lighthouse pass (home, shop, product)
- [ ] `loading.tsx` / `error.tsx` / `not-found.tsx` for main segments
- [ ] E2E suite green
- [ ] Coverage of `src/lib` + `src/server` ≥ 80%

## Phase 11 — Docs + deploy prep

- [ ] README (pitch, screenshots, features, stack, Mermaid diagram, key decisions, setup, tests, test cards)
- [ ] `docs/DEPLOY.md` (Vercel + Neon checklist)
- [ ] Final verification and report

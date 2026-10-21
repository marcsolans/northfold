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
- **Test databases are migrated with `prisma migrate deploy` and emptied with `TRUNCATE`, never `migrate reset`** — Prisma blocks destructive commands when driven by an AI agent; the deploy + truncate flow is also faster. `scripts/reset-test-db.ts` refuses any database not named `*_test`/`*_e2e`.
- **Better Auth models keep their default Prisma names and get snake_case via `@@map`/`@map`** — Better Auth's `modelName`/`fields` options rename the Prisma client API itself.
- **One Postgres-backed fixed-window rate limiter (`rate_limit_windows`, single atomic upsert)** — shared by Better Auth (`rateLimit.customStorage.consume`) and `placeOrder`; in-memory limits are per serverless instance and useless on Vercel.
- **Re-seeding never overwrites stock** — variants are upserted by SKU and stock is only set on creation, so `pnpm db:seed` is safe on a database with real inventory.
- **Shoes and kids' items reuse the `Size` enum (XS–XXL) with a size guide in the description** — the spec fixes the enum; a separate shoe-size enum would be a schema change outside it.
- **`OrderItem.variantId` is nullable (`ON DELETE SET NULL`)** — removing a variant in the admin must never break order history, which relies on snapshots anyway.
- **Orders carry `stockDeducted`, `needsReview` and `reviewReason`** — restocking on cancel must only return stock that was actually taken, and oversold Stripe payments need a visible admin flag.
- **Seed images come from images.unsplash.com (Unsplash License), each checked to load and to match its category** — the only image host reachable from the build VM; uploads go to Cloudinary.
- **Sign-in/sign-up call Better Auth from the browser (`authClient`), not through Server Actions** — `auth.api.*` calls skip Better Auth's rate limiter and origin checks; the HTTP route enforces both.
- **`requireAdmin()` bypasses Better Auth's 5-minute cookie cache** — a demoted admin or revoked session loses access on the next request, not after the cache expires.
- **Server Actions run inside `runAction()`** — one place maps authorization and user-facing errors to `ActionResult`, logs everything else with context and returns a generic message.
- **`proxy.ts` only checks for the presence of a session cookie** — it cannot validate sessions without a DB hit; pages, actions and route handlers do the real check. It also never redirects signed-in users away from auth pages (a stale cookie would loop).
- **No email verification** — no email provider is configured; Google sign-in into an existing password account therefore requires the password (Better Auth's safe default, `requireLocalEmailVerified`).
- **The storefront navbar does not read the session** — the account icon links to `/account` (the proxy/page sends anonymous users to sign-in), so the shared shell stays fully static and prerenderable.
- **Mobile menu and modals use the native `<dialog>` with `showModal()`** — focus trap, inert background, Escape and focus return come from the platform; the menu also closes itself when React's Activity hides its route.
- **Admin layout gate + per-query/per-action `requireAdmin()`** — the layout redirect is UX; the checks inside every admin read and mutation are the security boundary.
- **Unknown/archived product URLs render the 404 page with `noindex` but HTTP 200** — with Partial Prerendering the static shell streams before the page resolves, so `notFound()` cannot change the status; a real 404 would need a DB lookup in `proxy.ts` on every product request. Search engines treat `noindex` pages as soft 404s.
- **Catalog reads are cached with `"use cache"` + the `products` tag; stock-changing mutations call `revalidateTag("products", "max")`** — listings and product pages stay static/fast, and the cart and checkout always re-validate stock on the server, so a briefly stale "in stock" badge can never oversell.
- **Shop filters use `useOptimistic` + `router.push`** — clicks reflect instantly while the server re-renders from the URL; without JavaScript the filter panel is a plain GET form.

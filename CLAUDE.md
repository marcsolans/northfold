@AGENTS.md

# Northfold — project conventions

Northfold is a production-grade fashion e-commerce store: Next.js 16 (App Router, Cache
Components), React 19, TypeScript strict, Prisma 7 + PostgreSQL (Neon in production),
Better Auth, Stripe Checkout + webhooks, Cloudinary, Tailwind CSS v4, Zustand.

The spec this project implements and the phase plan live in `docs/PLAN.md`. Every
non-obvious choice is recorded as one line in `docs/DECISIONS.md` — add a line when you
make a new one.

## Commands

| Task                         | Command                                                  |
| ---------------------------- | -------------------------------------------------------- |
| Dev server                   | `pnpm dev`                                               |
| Phase gate (must be green)   | `pnpm lint && pnpm typecheck && pnpm test && pnpm build` |
| Unit tests only              | `pnpm test:unit`                                         |
| Integration tests (local PG) | `pnpm test:integration`                                  |
| Coverage                     | `pnpm test:coverage`                                     |
| E2E (Playwright)             | `pnpm test:e2e`                                          |
| New migration                | `pnpm db:migrate --name <name>`                          |
| Apply migrations (prod/CI)   | `pnpm db:deploy`                                         |
| Seed (idempotent)            | `pnpm db:seed`                                           |
| Promote `ADMIN_EMAILS` only  | `pnpm db:seed --admins-only`                             |
| Format                       | `pnpm format`                                            |

Prisma 7 refuses `migrate reset` when run by an AI agent: test databases are prepared with
`prisma migrate deploy` + `tsx scripts/reset-test-db.ts` (truncate; only `*_test`/`*_e2e` names).
After changing Better Auth options that affect the schema, regenerate with
`pnpm dlx auth@1.7.12 generate` (the CLI cannot load files importing `server-only`, so point it at
a temporary copy of `src/server/auth/auth.ts`) and keep the `@@map`/`@map` naming.

E2E builds the app and serves it on port 3100 against a freshly migrated and seeded
`northfold_e2e` (`scripts/e2e-server.sh`); the setup project signs up `ada@northfold.test` and
`admin@northfold.test` and promotes the admin through the seed. With a preinstalled Chromium set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` (here: `/opt/pw-browsers/chromium`). Every page is checked
for horizontal overflow and axe violations at 375 px and 1440 px (`e2e/support/pages.ts`) — add
new pages there.

Local PostgreSQL: `service postgresql start`. Databases: `northfold` (dev),
`northfold_test` (Vitest integration), `northfold_e2e` (Playwright). Role/password:
`northfold`/`northfold`.

Stripe webhooks locally:
`stripe listen --api-key "$STRIPE_SECRET_KEY" --forward-to localhost:3000/api/stripe/webhook`
(`--print-secret` prints the `whsec_...` value for `STRIPE_WEBHOOK_SECRET`).

## Architecture rules

- **Folders**: `src/app` (routes; groups `(store)`, `(auth)`, plus `account`, `admin`, `api`),
  `src/components/{ui,layout,store,account,auth,admin}`, `src/server/{actions,queries,auth,...}`,
  `src/lib` (pure helpers + SDK clients), `src/stores` (Zustand), `src/env.ts`.
- **Reads** happen in Server Components through functions in `src/server/queries`.
  **Mutations** go through Server Actions in `src/server/actions` (or route handlers for
  third-party callbacks such as the Stripe webhook).
- Every Server Action returns `ActionResult<T>` from `src/lib/action-result.ts`:
  `{ ok: true, data } | { ok: false, error, fieldErrors? }`. Never throw raw DB/Stripe
  errors to the client; log them with `logger` and return a safe message.
- **Authorization lives inside every action and route handler**: `requireAdmin()` for
  admin, `requireUser()` for account/checkout, plus an ownership check on every order or
  address read/write. Layouts and `proxy.ts` are UX only (optimistic redirects).
- **Validate every server input with Zod**. Schemas live in `src/lib/validators` and are
  shared by React Hook Form (client) and the actions (server).
- **Money**: Prisma `Decimal` in the DB, arithmetic only through `src/lib/money.ts`
  (decimal.js). Never use JS float math on money. Convert to integer cents only at the
  Stripe boundary (`toCents`). Format with `formatMoney` (Intl.NumberFormat).
  Decimals are not serialisable to Client Components: pass strings.
- **Never trust the client** for prices, totals, stock or roles. The cart store holds
  only `variantId`, `quantity` and a display snapshot; the server recomputes everything.
- **Stock changes** use conditional updates (`updateMany` where `stock >= qty`) inside a
  transaction; zero affected rows means out of stock → roll back.
- **Order status** transitions only via `src/lib/order-status.ts` (state machine).
- Orders snapshot product and address data; never join back to mutable rows for history.
- **Cache Components** is on: cacheable catalog reads use `"use cache"` + `cacheLife` +
  `cacheTag`; anything that reads cookies/headers/searchParams/per-user data renders inside
  `<Suspense>`. Mutations call `revalidateTag`/`updateTag`/`revalidatePath` for the data
  they change (tags are defined in `src/lib/cache-tags.ts`).
- Server-only modules start with `import "server-only"`.
- Env vars are read only through `src/env.ts` (Zod-validated, fails fast); the one
  exception is `process.env.NODE_ENV`, which Next.js inlines at build time.

## Code style

- TypeScript strict + `noUncheckedIndexedAccess`. No `any`, no `@ts-ignore`, no
  non-null assertions to silence errors, no `console.*` (use `src/lib/logger.ts`),
  no TODO comments, no dead code.
- Reuse the UI primitives in `src/components/ui` (Button, Input, Select, Badge, Card,
  Modal, Table, Skeleton, EmptyState, …) instead of ad-hoc markup.
- Every submit button has disabled + pending states; success/errors surface as toasts.
- Accessibility: semantic HTML, a label for every input, visible focus, keyboard support,
  meaningful `alt` text.
- Use the design tokens from `src/app/globals.css` (`bg-background`, `text-muted-foreground`,
  `border-border`, `bg-accent`, …); do not hard-code colours.
- Commits follow Conventional Commits (`feat:`, `fix:`, `chore:`, `test:`, `docs:`).

## Testing

- Unit tests sit next to the code as `*.test.ts`; integration tests (real Postgres) are
  `*.int.test.ts` and run against `northfold_test`, which the Vitest global setup resets
  with `prisma migrate reset`.
- E2E tests live in `e2e/` and run against a production build on `northfold_e2e`.
- Before committing a phase: run the full gate, and check each new page in a browser at
  375px and 1440px.

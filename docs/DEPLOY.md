# Deploying Northfold (Vercel + Neon)

This checklist takes the store from a fresh clone to a production deployment with card payments,
Google sign-in and image uploads. Every variable is documented in [`.env.example`](../.env.example)
and validated when the app boots (`src/env.ts`), so a missing or malformed value fails the deploy
with a readable message instead of a broken store.

## 1. Database (Neon)

1. Create a project at [neon.tech](https://neon.tech) (PostgreSQL 16 or newer) in the region
   closest to your Vercel functions.
2. Copy both connection strings from **Connect**:
   - **Pooled** (the host contains `-pooler`): becomes `DATABASE_URL`, used at runtime.
   - **Direct** (no `-pooler`): becomes `DIRECT_URL`, used only by `prisma migrate deploy`.
3. Apply the schema and load the catalog from your machine before the first deploy. Product
   pages and the home page are prerendered from the database at build time, so they need data
   to exist first.

   ```bash
   DATABASE_URL="<direct url>" DIRECT_URL="<direct url>" pnpm db:deploy
   DATABASE_URL="<direct url>" pnpm db:seed      # 26 demo products; safe to re-run
   ```

   Skip the seed if you will add your own products in the admin. An empty catalog builds fine.

## 2. Vercel project

1. **Add New → Project** and import the GitHub repository. Vercel detects Next.js and pnpm (from
   `pnpm-lock.yaml`). To build with the exact pnpm version pinned in `packageManager`, add the
   environment variable `ENABLE_EXPERIMENTAL_COREPACK=1`.
2. The build command comes from [`vercel.json`](../vercel.json): `pnpm vercel-build`, which runs
   `prisma migrate deploy && next build`. Every deployment applies pending migrations before the
   new code takes traffic. `postinstall` regenerates the Prisma client.
3. Node.js version: 22.x (Project Settings → Build and Deployment). The repository requires
   `>= 22.12`.
4. Add the environment variables below, then deploy.

### Environment variables

Set them in **Project Settings → Environment Variables**. Values marked _same_ are identical in
every environment.

| Variable                | Production                                | Preview                                            | Notes                                                    |
| ----------------------- | ----------------------------------------- | -------------------------------------------------- | -------------------------------------------------------- |
| `DATABASE_URL`          | Neon **pooled** URL                       | Pooled URL of a separate Neon branch (recommended) | Runtime queries                                          |
| `DIRECT_URL`            | Neon **direct** URL                       | Direct URL of that branch                          | Migrations during the build                              |
| `NEXT_PUBLIC_APP_URL`   | `https://<your-domain>`                   | The preview's stable URL (see below)               | Stripe redirects, sitemap, metadata                      |
| `BETTER_AUTH_URL`       | Same value as `NEXT_PUBLIC_APP_URL`       | Same value as `NEXT_PUBLIC_APP_URL`                | Auth callbacks and origin checks                         |
| `BETTER_AUTH_SECRET`    | `openssl rand -base64 32`                 | A different random value                           | At least 32 characters; never reuse between environments |
| `STRIPE_SECRET_KEY`     | `sk_live_…` (or `sk_test_…` until launch) | `sk_test_…`                                        | Optional: enables card payments                          |
| `STRIPE_WEBHOOK_SECRET` | `whsec_…` of the production endpoint      | `whsec_…` of a test-mode endpoint                  | Required whenever `STRIPE_SECRET_KEY` is set             |
| `GOOGLE_CLIENT_ID`      | OAuth client id                           | _same_ (add the preview redirect URI)              | Optional: set both or neither                            |
| `GOOGLE_CLIENT_SECRET`  | OAuth client secret                       | _same_                                             |                                                          |
| `CLOUDINARY_CLOUD_NAME` | Cloud name                                | _same_                                             | Optional: set all three or none                          |
| `CLOUDINARY_API_KEY`    | API key                                   | _same_                                             |                                                          |
| `CLOUDINARY_API_SECRET` | API secret                                | _same_                                             |                                                          |
| `ADMIN_EMAILS`          | Not needed at runtime                     | Not needed                                         | Only read by `pnpm db:seed` (see step 7)                 |

**Preview deployments and auth.** Better Auth only trusts requests from
`NEXT_PUBLIC_APP_URL`/`BETTER_AUTH_URL`, so signing in works on the URL those variables name.
For previews you have two options:

- Point both at a stable branch alias (for example `https://northfold-git-staging-<team>.vercel.app`).
- Accept that sign-in only works on Production, and use previews for the storefront.

Give previews their own Neon branch so test orders never reach production data.

## 3. Stripe

1. **Developers → Webhooks → Add endpoint** (shown as _Add destination_ in Workbench):
   - URL: `https://<your-domain>/api/stripe/webhook`
   - API version: `2026-09-30.endive`, the version pinned by the `stripe` SDK in this repository.
   - Events:
     - `checkout.session.completed`
     - `checkout.session.async_payment_succeeded`
     - `checkout.session.async_payment_failed`
     - `checkout.session.expired`
2. Copy the endpoint's **Signing secret** into `STRIPE_WEBHOOK_SECRET`, and the matching secret
   key into `STRIPE_SECRET_KEY`. Test and live mode have separate endpoints and secrets.
3. Redeploy so the new variables are picked up.

The route answers `400` to unsigned or tampered requests and `503` when Stripe isn't configured.
A duplicate delivery is acknowledged without being processed again.

## 4. Google sign-in (optional)

1. Google Cloud Console → **APIs & Services → Credentials → Create credentials → OAuth client
   ID** → _Web application_.
2. **Authorised JavaScript origins:** `https://<your-domain>`.
3. **Authorised redirect URIs:** `https://<your-domain>/api/auth/callback/google`. That is
   `<BETTER_AUTH_URL>/api/auth/callback/google`, plus the same path on any preview URL you use.
4. Put the client id and secret in `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. The "Continue
   with Google" button appears only when both are set.

## 5. Cloudinary (optional)

Cloudinary Console → **Settings → API Keys**, then set `CLOUDINARY_CLOUD_NAME`,
`CLOUDINARY_API_KEY` and `CLOUDINARY_API_SECRET`.

- Uploads are signed on the server and stored under `northfold/products`.
- `next.config.ts` allows images from `res.cloudinary.com/<cloud name>`, so redeploy after
  setting the cloud name.
- Without Cloudinary, admins can still add images by URL from Cloudinary or Unsplash.

## 6. Deploy and verify

After the first deployment:

```bash
curl -sI https://<your-domain> | grep -iE "content-security-policy|strict-transport|x-frame"
```

- [ ] Security headers are present: CSP, `Strict-Transport-Security`, `X-Frame-Options: DENY`.
- [ ] `/sitemap.xml` lists the products and `/robots.txt` points to it.
- [ ] Sign up, add a product to the bag and place a **cash-on-delivery** order.
- [ ] With Stripe in test mode, pay with `4242 4242 4242 4242`:
  - the success page switches to "confirmed";
  - Stripe shows the webhook delivery as `200`;
  - the order is **Paid** and **Processing** in the account and the admin.
- [ ] Pay with `4000 0000 0000 0002` (declined): no order is marked paid and no stock is taken.

## 7. Create the first admin

Roles cannot be set through sign-up or any form, by design. To promote an account:

1. Sign up on the deployed site with the email that should become admin.
2. From your machine, promote that email in the production database. `--admins-only` skips
   the catalog, so products edited in the admin are left alone.

   ```bash
   DATABASE_URL="<direct url>" ADMIN_EMAILS="you@example.com" pnpm db:seed --admins-only
   ```

3. Reload the site: **Account → Admin dashboard**, or go to `/admin`.

To demote an admin, set their `role` back to `USER` in the database (for example with
`pnpm db:studio`). It takes effect on their next admin request, because admin checks always read
the role fresh.

## 8. Going live

- Switch to Stripe **live** keys and create a live-mode webhook endpoint with the same events.
- Set your custom domain in Vercel and update `NEXT_PUBLIC_APP_URL`, `BETTER_AUTH_URL`, the
  Stripe webhook URL and the Google OAuth origins and redirect URI to match.
- HSTS (`max-age=63072000; includeSubDomains; preload`) and `upgrade-insecure-requests` are sent
  automatically once `NEXT_PUBLIC_APP_URL` is `https://`. Only submit the domain to the HSTS
  preload list once every subdomain serves HTTPS.

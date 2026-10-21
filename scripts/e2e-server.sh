#!/usr/bin/env bash
# Starts the store for Playwright: migrate + empty the e2e database, seed it, build and serve.
set -euo pipefail

pnpm exec prisma migrate deploy
pnpm exec tsx scripts/reset-test-db.ts
pnpm exec tsx prisma/seed.ts
pnpm exec next build
exec pnpm exec next start -p "${PORT:-3100}"

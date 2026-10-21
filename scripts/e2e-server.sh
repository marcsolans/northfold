#!/usr/bin/env bash
# Starts the store for Playwright: reset the e2e database, seed it, build and serve.
set -euo pipefail

pnpm exec prisma migrate reset --force
pnpm exec tsx prisma/seed.ts
pnpm exec next build
exec pnpm exec next start -p "${PORT:-3100}"

# Messer web (Next.js standalone). Build context: repository root.
FROM node:22-slim AS deps
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY apps/web/scripts apps/web/scripts
COPY packages/ui/package.json packages/ui/package.json
COPY packages/messer-sdk-ts/package.json packages/messer-sdk-ts/package.json
COPY tests/e2e/package.json tests/e2e/package.json
RUN pnpm install --frozen-lockfile --filter @messer/web...

FROM deps AS build
COPY packages/ui packages/ui
COPY apps/web apps/web
ARG MESSER_API_URL=http://api:8000
ARG NEXT_PUBLIC_POSTHOG_KEY=
ARG NEXT_PUBLIC_POSTHOG_HOST=https://eu.i.posthog.com
ARG NEXT_PUBLIC_SENTRY_DSN=
ENV MESSER_API_URL=$MESSER_API_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm --filter @messer/web build

FROM node:22-slim
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
RUN useradd --create-home --uid 10001 messer
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /repo/apps/web/public ./apps/web/public
COPY --from=build /repo/apps/web/messages ./apps/web/messages
USER messer
EXPOSE 3000
CMD ["node", "apps/web/server.js"]

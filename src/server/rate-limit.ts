import "server-only";

import { prisma } from "@/lib/prisma";

export interface RateLimitRule {
  /** Window length in seconds. */
  window: number;
  /** Maximum requests allowed per window. */
  max: number;
}

export interface RateLimitResult {
  allowed: boolean;
  /** Seconds until the window resets when not allowed. */
  retryAfter: number | null;
}

/**
 * Fixed-window rate limiter backed by Postgres. A single atomic upsert records the request and
 * returns the window state, so concurrent requests on any number of serverless instances are
 * counted correctly. Used for placeOrder and as Better Auth's rate-limit storage.
 */
export async function consumeRateLimit(key: string, rule: RateLimitRule): Promise<RateLimitResult> {
  const rows = await prisma.$queryRaw<{ count: number; retry_after: number }[]>`
    INSERT INTO rate_limit_windows (key, count, window_start, created_at, updated_at)
    VALUES (${key}, 1, now(), now(), now())
    ON CONFLICT (key) DO UPDATE SET
      count = CASE
        WHEN rate_limit_windows.window_start <= now() - make_interval(secs => ${rule.window})
        THEN 1 ELSE rate_limit_windows.count + 1 END,
      window_start = CASE
        WHEN rate_limit_windows.window_start <= now() - make_interval(secs => ${rule.window})
        THEN now() ELSE rate_limit_windows.window_start END,
      updated_at = now()
    RETURNING
      count,
      CEIL(EXTRACT(EPOCH FROM (window_start + make_interval(secs => ${rule.window}) - now())))::int
        AS retry_after
  `;
  const row = rows[0];
  if (!row) return { allowed: true, retryAfter: null };
  const allowed = row.count <= rule.max;
  return { allowed, retryAfter: allowed ? null : Math.max(1, row.retry_after) };
}

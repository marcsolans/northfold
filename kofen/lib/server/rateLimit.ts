/**
 * Minimal in-memory sliding-window rate limiter.
 *
 * Per server instance only: counts reset on a cold start and are not shared
 * between Vercel instances. Good enough to blunt casual abuse of a contact form;
 * swap for a shared store (e.g. Upstash Redis) if that ever matters.
 */
const hits = new Map<string, number[]>();
let lastSweep = 0;

export function rateLimit(key: string, { limit = 5, windowMs = 10 * 60_000 } = {}) {
  const now = Date.now();
  if (now - lastSweep > windowMs) {
    for (const [k, times] of hits) if (times.every((t) => now - t > windowMs)) hits.delete(k);
    lastSweep = now;
  }
  const recent = (hits.get(key) ?? []).filter((t) => now - t < windowMs);
  if (recent.length >= limit) {
    hits.set(key, recent);
    return { ok: false as const, retryAfter: Math.ceil((windowMs - (now - recent[0])) / 1000) };
  }
  recent.push(now);
  hits.set(key, recent);
  return { ok: true as const };
}

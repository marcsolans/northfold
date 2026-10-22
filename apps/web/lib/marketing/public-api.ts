/**
 * Server-side reads of public API endpoints for the marketing site (plans, credit packs, credit pricing,
 * status). Cached by Next's data cache and revalidated in the background; on failure the pages show an
 * explicit "unavailable" message instead of invented values.
 */

export interface PlanLimits {
  seats: number;
  projects: number;
  runs_month: number;
  credits_month: number;
  storage_gb: number;
  features: string[];
}

export interface PublicPlan {
  id: string;
  name: string;
  description: string;
  price_month_eur: string;
  price_year_eur: string;
  price_is_starting: boolean;
  self_serve: boolean;
  sort_order: number;
  limits: PlanLimits;
}

export interface CreditPack {
  id: string;
  credits: number;
  price_eur: string;
}

export interface CreditPricing {
  credit_usd: string;
  margin_pct: string;
  models: {
    tier: "fast" | "standard" | "powerful";
    model: string;
    display_name: string;
    input_usd_per_mtok: string;
    output_usd_per_mtok: string;
    input_credits_per_mtok: string;
    output_credits_per_mtok: string;
  }[];
}

export type ServiceStatus = "operational" | "degraded" | "down" | "unknown";

export interface PublicStatus {
  status: ServiceStatus;
  updated_at: string | null;
  generated_at: string;
  history_days: number;
  services: {
    key: string;
    status: ServiceStatus;
    latency_ms: number | null;
    checked_at: string | null;
    uptime_90d: number | null;
    days: { date: string; status: "operational" | "degraded" | "down" | "no_data"; uptime: number | null }[];
  }[];
  incidents: { service: string; status: "degraded" | "down"; started_at: string; resolved_at: string | null }[];
}

export type Fetched<T> = { ok: true; data: T } | { ok: false };

// Short enough that an API outage never makes marketing pages slow (they render their fallback instead).
const TIMEOUT_MS = 2500;

function apiBase(): string {
  return (process.env.MESSER_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

export async function fetchPublic<T>(path: string, revalidate: number): Promise<Fetched<T>> {
  try {
    const res = await fetch(`${apiBase()}/api/v1${path}`, {
      headers: { Accept: "application/json" },
      next: { revalidate },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) return { ok: false };
    return { ok: true, data: (await res.json()) as T };
  } catch {
    return { ok: false };
  }
}

function isPlan(value: unknown): value is PublicPlan {
  if (typeof value !== "object" || value === null) return false;
  const p = value as Partial<PublicPlan>;
  return (
    typeof p.id === "string" &&
    typeof p.name === "string" &&
    p.price_month_eur !== undefined &&
    p.price_year_eur !== undefined &&
    typeof p.limits === "object" &&
    p.limits !== null
  );
}

export async function getPlans(): Promise<Fetched<PublicPlan[]>> {
  const res = await fetchPublic<unknown>("/plans", 300);
  if (!res.ok || !Array.isArray(res.data)) return { ok: false };
  const plans = res.data.filter(isPlan).map((p) => ({
    ...p,
    price_month_eur: String(p.price_month_eur),
    price_year_eur: String(p.price_year_eur),
    limits: { ...p.limits, features: Array.isArray(p.limits.features) ? p.limits.features : [] },
  }));
  if (!plans.length) return { ok: false };
  return { ok: true, data: plans.sort((a, b) => a.sort_order - b.sort_order) };
}

export async function getCreditPacks(): Promise<Fetched<CreditPack[]>> {
  const res = await fetchPublic<unknown>("/credit-packs", 300);
  if (!res.ok || !Array.isArray(res.data)) return { ok: false };
  const packs = res.data.filter(
    (p): p is CreditPack =>
      typeof p === "object" && p !== null && typeof (p as CreditPack).id === "string" && Number.isFinite(Number((p as CreditPack).credits)),
  );
  return packs.length ? { ok: true, data: packs.map((p) => ({ ...p, price_eur: String(p.price_eur) })) } : { ok: false };
}

export function getCreditPricing(): Promise<Fetched<CreditPricing>> {
  return fetchPublic<CreditPricing>("/site/credits", 300);
}

export function getPublicStatus(): Promise<Fetched<PublicStatus>> {
  return fetchPublic<PublicStatus>("/status/public", 30);
}

export const UNLIMITED = -1;

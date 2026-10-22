/** Formatting helpers shared by Studio, traces and approvals. */

import type { StatusTone } from "@messer/ui";

import type { ApprovalStatus, Money, RunModel, RunStatus } from "./types";

/** Run ids travel as 32-char hex in stream events and as dashed UUIDs in the REST API. */
export function toUuid(id: string): string {
  const hex = id.replace(/-/g, "").toLowerCase();
  if (!/^[0-9a-f]{32}$/.test(hex)) return id;
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function sameId(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  return a.replace(/-/g, "").toLowerCase() === b.replace(/-/g, "").toLowerCase();
}

export function shortHash(commit: string | null | undefined): string {
  return commit ? commit.slice(0, 7) : "—";
}

export function toNumber(value: Money | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

export function formatCredits(value: Money | null | undefined, locale = "es-ES"): string {
  const n = toNumber(value);
  return new Intl.NumberFormat(locale, { maximumFractionDigits: n !== 0 && Math.abs(n) < 1 ? 4 : 2 }).format(n);
}

export function formatTokens(value: number, locale = "es-ES"): string {
  return new Intl.NumberFormat(locale, { notation: value >= 100_000 ? "compact" : "standard" }).format(value);
}

export const RUN_STATUS_TONE: Record<RunStatus, StatusTone> = {
  running: "info",
  success: "success",
  paused: "warning",
  error: "danger",
  timeout: "danger",
  blocked: "danger",
  cancelled: "neutral",
  budget_exceeded: "danger",
};

export function runStatusTone(status: string): StatusTone {
  return RUN_STATUS_TONE[status as RunStatus] ?? "neutral";
}

export const APPROVAL_STATUS_TONE: Record<ApprovalStatus, StatusTone> = {
  pending: "warning",
  approved: "success",
  denied: "danger",
  expired: "neutral",
};

export function modelNames(models: (RunModel | string)[] | null | undefined): string[] {
  const out: string[] = [];
  for (const m of models ?? []) {
    const name = typeof m === "string" ? m : m.model;
    if (name && !out.includes(name)) out.push(name);
  }
  return out;
}

/** Compact JSON for inline previews. */
export function previewJson(value: unknown, max = 140): string {
  let text: string;
  if (typeof value === "string") text = value;
  else {
    try {
      text = JSON.stringify(value);
    } catch {
      text = String(value);
    }
  }
  if (text === undefined) return "";
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** `datetime-local`/`date` input → ISO timestamp for API filters. */
export function dateInputToIso(value: string, endOfDay = false): string | undefined {
  if (!value) return undefined;
  const d = new Date(`${value}T00:00:00`);
  if (Number.isNaN(d.getTime())) return undefined;
  if (endOfDay) d.setDate(d.getDate() + 1);
  return d.toISOString();
}

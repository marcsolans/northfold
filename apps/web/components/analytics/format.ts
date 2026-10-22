import { formatDuration, formatNumber, formatUsd } from "@/lib/format";

import type { Bucket, MetricUnit } from "./types";

export function compactNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { notation: Math.abs(value) >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

/** Ratio 0..1 → "83,3 %". */
export function formatRatio(value: number | null | undefined, locale: string, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value);
}

/** Value of a metric in its unit (percent values are already 0..100). */
export function formatMetric(value: number | null | undefined, unit: MetricUnit, locale: string): string {
  if (value === null || value === undefined) return "—";
  switch (unit) {
    case "percent":
      return `${formatNumber(value, locale, 1)} %`;
    case "ms":
      return formatDuration(value);
    case "usd":
      return formatUsd(value, locale);
    case "credits":
      return formatNumber(value, locale, 2);
    case "tokens":
      return compactNumber(value, locale);
    default:
      return formatNumber(value, locale, 2);
  }
}

export function bucketLabel(iso: string, bucket: Bucket, locale: string, long = false): string {
  const d = new Date(iso);
  if (bucket === "hour") {
    return new Intl.DateTimeFormat(locale, long ? { dateStyle: "medium", timeStyle: "short" } : { hour: "2-digit", minute: "2-digit" }).format(d);
  }
  return new Intl.DateTimeFormat(locale, long ? { dateStyle: "medium" } : { day: "numeric", month: "short" }).format(d);
}

/** Relative change between two values; null when there is no baseline. */
export function delta(current: number | null, previous: number | null): number | null {
  if (current === null || previous === null || previous === 0) return null;
  return (current - previous) / Math.abs(previous);
}

export function traceHref(projectId: string, runId: string): string {
  return `/app/projects/${projectId}/traces/${runId}`;
}

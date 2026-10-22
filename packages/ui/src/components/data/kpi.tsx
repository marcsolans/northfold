import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import * as React from "react";

import { cn } from "../../lib/cn";
import { Skeleton } from "../skeleton";
import type { DataStateLabels } from "./data-state";
import { formatValue, toNumber } from "./format";

export interface KpiCardProps {
  label?: React.ReactNode;
  value: unknown;
  format?: "number" | "currency" | "percent" | "text";
  currency?: string;
  decimals?: number | null;
  delta?: unknown;
  deltaFormat?: "number" | "percent";
  trend?: "up_is_good" | "down_is_good";
  hint?: React.ReactNode;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  labels: DataStateLabels & { increase: string; decrease: string };
  locale?: string;
  className?: string;
}

/** A single headline number (stat tile) with an optional signed change. */
export function KpiCard({
  label,
  value,
  format = "number",
  currency = "EUR",
  decimals,
  delta,
  deltaFormat = "percent",
  trend = "up_is_good",
  hint,
  loading,
  error,
  onRetry,
  labels,
  locale = "es-ES",
  className,
}: KpiCardProps) {
  const n = toNumber(value);
  let text: string;
  if (format === "text" || n === null) {
    text = value === null || value === undefined || value === "" ? "—" : String(value);
  } else {
    const compactable = Math.abs(n) >= 100_000 && (decimals === null || decimals === undefined);
    text = compactable
      ? new Intl.NumberFormat(locale, {
          notation: "compact",
          maximumFractionDigits: 1,
          ...(format === "currency" ? { style: "currency", currency } : format === "percent" ? { style: "percent" } : {}),
        }).format(n)
      : formatValue(n, format, { locale, currency, decimals });
  }
  const d = toNumber(delta);
  const good = d !== null && d !== 0 && (trend === "up_is_good" ? d > 0 : d < 0);
  const deltaText =
    d === null
      ? null
      : `${d > 0 ? "+" : ""}${formatValue(d, deltaFormat === "percent" ? "percent" : "number", { locale })}`;

  return (
    <div className={cn("flex h-full min-h-0 flex-col justify-center gap-1", className)}>
      {label ? <p className="truncate text-xs font-medium uppercase tracking-wide text-fg-subtle">{label}</p> : null}
      {loading ? (
        <div role="status" aria-label={labels.loading} className="flex flex-col gap-1.5">
          <Skeleton className="h-8 w-28" />
          <Skeleton className="h-3 w-20" />
        </div>
      ) : error ? (
        <div role="alert" className="text-sm">
          <p className="font-semibold text-danger">{labels.errorTitle}</p>
          <p className="text-fg-muted">{error}</p>
          {onRetry ? (
            <button type="button" onClick={onRetry} className="font-medium text-danger underline underline-offset-4">
              {labels.retry}
            </button>
          ) : null}
        </div>
      ) : (
        <>
          <p className="truncate text-xl font-semibold leading-tight text-fg" title={text}>
            {text}
          </p>
          <div className="flex min-w-0 items-center gap-2 text-xs">
            {deltaText ? (
              <span
                className={cn(
                  "inline-flex items-center gap-0.5 font-medium",
                  d === 0 ? "text-fg-muted" : good ? "text-success" : "text-danger",
                )}
              >
                {d !== null && d > 0 ? <ArrowUpRight className="size-3.5" aria-hidden /> : null}
                {d !== null && d < 0 ? <ArrowDownRight className="size-3.5" aria-hidden /> : null}
                <span className="sr-only">{d !== null && d > 0 ? labels.increase : labels.decrease}</span>
                <span className="tabular">{deltaText}</span>
              </span>
            ) : null}
            {hint ? <span className="truncate text-fg-muted">{hint}</span> : null}
          </div>
        </>
      )}
    </div>
  );
}

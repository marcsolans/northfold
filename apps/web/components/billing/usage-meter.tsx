"use client";

import { cn } from "@messer/ui";
import { useTranslations } from "next-intl";

/** Usage vs plan limit. ``limit`` −1 means unlimited (no bar, just the figure). */
export function UsageMeter({
  label,
  used,
  limit,
  format,
  className,
}: {
  label: string;
  used: number;
  limit: number;
  format: (value: number) => string;
  className?: string;
}) {
  const t = useTranslations("billing");
  const unlimited = limit === -1;
  const pct = unlimited || limit <= 0 ? 0 : Math.min(100, Math.round((used / limit) * 100));
  const tone = pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-warning" : "bg-fg";
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="text-fg-muted">{label}</span>
        <span className="tabular font-medium">
          {format(used)}
          <span className="text-fg-subtle"> / {unlimited ? t("usage.unlimited") : format(limit)}</span>
        </span>
      </div>
      {unlimited ? (
        <div className="h-1.5 rounded-full bg-muted" aria-hidden />
      ) : (
        <div
          className="h-1.5 overflow-hidden rounded-full bg-muted"
          role="meter"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={limit}
          aria-valuenow={Math.min(used, limit)}
        >
          <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}

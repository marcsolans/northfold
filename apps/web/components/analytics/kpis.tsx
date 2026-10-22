"use client";

import { Skeleton, cn } from "@messer/ui";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import type * as React from "react";

import { formatDuration, formatNumber, formatUsd, localeTag } from "@/lib/format";

import { delta, formatRatio } from "./format";
import type { Overview } from "./types";

type Direction = "up-good" | "down-good" | "neutral";

interface TileProps {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  /** ``null``: no previous period to compare with; omitted: the tile has no comparison. */
  change?: { value: number; kind: "relative" | "points" } | null;
  direction: Direction;
}

function Change({ change, direction }: { change: NonNullable<TileProps["change"]> | null; direction: Direction }) {
  const t = useTranslations("analytics.kpis");
  const locale = localeTag(useLocale());
  if (change === null || !Number.isFinite(change.value)) {
    return <p className="mt-1 text-xs text-fg-subtle">{t("noPrevious")}</p>;
  }
  const v = change.value;
  const flat = Math.abs(v) < (change.kind === "points" ? 0.0005 : 0.005);
  const up = v > 0;
  const good = flat || direction === "neutral" ? null : direction === "up-good" ? up : !up;
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  const text =
    change.kind === "points"
      ? `${up ? "+" : ""}${formatNumber(v * 100, locale, 1)} pp`
      : `${up ? "+" : ""}${new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(v)}`;
  return (
    <p
      className={cn(
        "mt-1 flex items-center gap-1 text-xs",
        good === null ? "text-fg-muted" : good ? "text-success" : "text-danger",
      )}
    >
      <Icon className="size-3.5" aria-hidden />
      <span className="sr-only">{up ? t("up") : flat ? t("flat") : t("down")}</span>
      {flat ? t("vsPreviousFlat") : t("vsPrevious", { delta: text })}
    </p>
  );
}

function Tile({ label, value, hint, change, direction }: TileProps) {
  return (
    <div className="rounded-md border border-border bg-surface px-4 py-3">
      <p className="text-xs font-medium text-fg-subtle">{label}</p>
      <p className="mt-1 text-xl font-semibold leading-tight text-fg">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-fg-muted">{hint}</p> : null}
      {change !== undefined ? <Change change={change} direction={direction} /> : null}
    </div>
  );
}

function rel(cur: number | null, prev: number | null): NonNullable<TileProps["change"]> | null {
  const d = delta(cur, prev);
  return d === null ? null : { value: d, kind: "relative" };
}

function points(cur: number | null, prev: number | null, prevRuns: number): NonNullable<TileProps["change"]> | null {
  if (cur === null || prev === null || prevRuns === 0) return null;
  return { value: cur - prev, kind: "points" };
}

export function KpiGrid({ data }: { data: Overview }) {
  const t = useTranslations("analytics.kpis");
  const locale = localeTag(useLocale());
  const k = data.kpis;
  const p = data.previous;
  const cost = Number(k.cost_usd);
  const prevCost = Number(p.cost_usd);
  const prevRuns = p.runs;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Tile
        label={t("runs")}
        value={formatNumber(k.runs, locale)}
        hint={t("errors", { count: k.errors })}
        change={rel(k.runs, prevRuns || null)}
        direction="up-good"
      />
      <Tile
        label={t("cost")}
        value={formatUsd(cost, locale)}
        hint={t("credits", { credits: formatNumber(Number(k.credits), locale, 2) })}
        change={rel(cost, prevCost || null)}
        direction="neutral"
      />
      <Tile label={t("users")} value={formatNumber(k.users, locale)} change={rel(k.users, p.users || null)} direction="up-good" />
      <Tile
        label={t("successRate")}
        value={formatRatio(k.success_rate, locale)}
        hint={t("terminal", { count: k.terminal })}
        change={points(k.success_rate, p.success_rate, prevRuns)}
        direction="up-good"
      />
      <Tile label={t("p50")} value={formatDuration(k.p50_ms)} change={rel(k.p50_ms, p.p50_ms)} direction="down-good" />
      <Tile label={t("p95")} value={formatDuration(k.p95_ms)} change={rel(k.p95_ms, p.p95_ms)} direction="down-good" />
      <Tile
        label={t("feedback")}
        value={formatRatio(data.feedback.up_ratio, locale, 0)}
        hint={data.feedback.total ? t("feedbackCount", { up: data.feedback.up, down: data.feedback.down }) : t("noFeedback")}
        direction="up-good"
      />
      <Tile
        label={t("costPerRun")}
        value={k.runs ? formatUsd(cost / k.runs, locale) : "—"}
        change={rel(k.runs ? cost / k.runs : null, prevRuns ? prevCost / prevRuns : null)}
        direction="down-good"
      />
    </div>
  );
}

export function KpiGridSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-hidden>
      {Array.from({ length: 8 }, (_, i) => (
        <Skeleton key={i} className="h-[92px]" />
      ))}
    </div>
  );
}

"use client";

import { Card, CardHeader, cn } from "@messer/ui";
import { useLocale, useTranslations } from "next-intl";
import type * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  Rectangle,
  ResponsiveContainer,
  Tooltip,
  type TooltipContentProps,
  XAxis,
  YAxis,
} from "recharts";

import { formatDuration, formatNumber, formatUsd, localeTag } from "@/lib/format";

import { bucketLabel, compactNumber } from "./format";
import type { Bucket, SeriesPoint } from "./types";

/**
 * Chart colors: slots 1–3 of the validated categorical palette (blue, orange, aqua), stepped separately for the
 * dark surface (validated light on #ffffff and dark on #161616). Text always uses text tokens; colors only
 * identify series. Status colors are never used for series.
 */
export const VIZ =
  "[--series-1:#2a78d6] [--series-2:#eb6834] [--series-3:#1baf7a] dark:[--series-1:#3987e5] dark:[--series-2:#d95926] dark:[--series-3:#199e70]";
const AXIS = { fontSize: 12, fill: "var(--fg-subtle)" } as const;
const LEGEND_STYLE = { fontSize: 12, paddingBottom: 4 } as const;

/** Legend text wears text tokens (the colored key beside it carries identity); series keep declaration order. */
function legendText(value: string) {
  return <span className="text-fg-muted">{value}</span>;
}
const GRID = "var(--border)";

export function ChartCard({
  title,
  description,
  children,
  className,
  dimmed,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  dimmed?: boolean;
}) {
  return (
    <Card className={cn("flex min-w-0 flex-col", className)}>
      <CardHeader title={title} description={description} />
      <div className={cn("p-4 transition-opacity", VIZ, dimmed && "opacity-60")}>{children}</div>
    </Card>
  );
}

function SeriesTooltip({
  active,
  payload,
  label,
  bucket,
  format,
}: TooltipContentProps & { bucket: Bucket; format: (value: number) => string }) {
  const locale = localeTag(useLocale());
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 text-fg-muted">{bucketLabel(String(label ?? ""), bucket, locale, true)}</p>
      {payload.map((p) => (
        <p key={String(p.dataKey)} className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-0.5 w-3 rounded-full" style={{ background: p.color }} />
          <span className="tabular font-semibold text-fg">{p.value === null || p.value === undefined ? "—" : format(Number(p.value))}</span>
          <span className="text-fg-muted">{p.name}</span>
        </p>
      ))}
    </div>
  );
}

function TableView({ summary, children }: { summary: string; children: React.ReactNode }) {
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer text-xs text-fg-muted hover:text-fg">{summary}</summary>
      <div className="mt-2 max-h-64 overflow-auto">{children}</div>
    </details>
  );
}

function xAxis(bucket: Bucket, locale: string) {
  return (
    <XAxis
      dataKey="t"
      tickFormatter={(v: string) => bucketLabel(v, bucket, locale)}
      tick={AXIS}
      tickLine={false}
      axisLine={{ stroke: "var(--border-strong)" }}
      minTickGap={24}
    />
  );
}

interface SegmentProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  fill?: string;
  payload?: Record<string, number>;
}

/** Stacked segment: 2px surface gap, rounded data-end only on the topmost non-empty segment. */
function segment(order: readonly string[], key: string) {
  const SegmentShape = (props: unknown) => {
    const p = props as SegmentProps;
    const idx = order.indexOf(key);
    const isTop = order.slice(idx + 1).every((k) => !p.payload?.[k]);
    return (
      <Rectangle
        x={p.x}
        y={p.y}
        width={p.width}
        height={p.height}
        fill={p.fill}
        radius={isTop ? [4, 4, 0, 0] : 0}
        stroke="var(--surface)"
        strokeWidth={1}
      />
    );
  };
  return SegmentShape;
}

const RUN_SERIES = ["success", "failed", "other"] as const;

export function RunsChart({ points, bucket, dimmed }: { points: SeriesPoint[]; bucket: Bucket; dimmed?: boolean }) {
  const t = useTranslations("analytics.charts");
  const locale = localeTag(useLocale());
  const rows = points.map((p) => ({ t: p.t, success: p.success, failed: p.errors, other: Math.max(0, p.runs - p.success - p.errors) }));
  const hasOther = rows.some((r) => r.other > 0);
  const order = hasOther ? RUN_SERIES : RUN_SERIES.slice(0, 2);
  return (
    <ChartCard title={t("runs")} description={t("runsDescription", { bucket: t(`buckets.${bucket}`) })} dimmed={dimmed}>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            {xAxis(bucket, locale)}
            <YAxis allowDecimals={false} tick={AXIS} tickLine={false} axisLine={false} width={44} tickFormatter={(v: number) => compactNumber(v, locale)} />
            <Tooltip
              cursor={{ fill: "var(--muted)" }}
              content={(props) => <SeriesTooltip {...props} bucket={bucket} format={(v) => formatNumber(v, locale)} />}
            />
            <Legend verticalAlign="top" align="right" iconType="square" iconSize={8} itemSorter={null} formatter={legendText} wrapperStyle={LEGEND_STYLE} />
            <Bar isAnimationActive={false} dataKey="success" name={t("success")} stackId="runs" fill="var(--series-1)" maxBarSize={24} shape={segment(order, "success")} />
            <Bar isAnimationActive={false} dataKey="failed" name={t("failed")} stackId="runs" fill="var(--series-2)" maxBarSize={24} shape={segment(order, "failed")} />
            {hasOther ? (
              <Bar isAnimationActive={false} dataKey="other" name={t("other")} stackId="runs" fill="var(--series-3)" maxBarSize={24} shape={segment(order, "other")} />
            ) : null}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableView summary={t("showTable")}>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-fg-subtle">
              <th className="py-1 pr-3 font-medium">{t("time")}</th>
              <th className="py-1 pr-3 text-right font-medium">{t("success")}</th>
              <th className="py-1 pr-3 text-right font-medium">{t("failed")}</th>
              <th className="py-1 text-right font-medium">{t("other")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.t} className="border-t border-border">
                <td className="py-1 pr-3">{bucketLabel(r.t, bucket, locale, true)}</td>
                <td className="tabular py-1 pr-3 text-right">{r.success}</td>
                <td className="tabular py-1 pr-3 text-right">{r.failed}</td>
                <td className="tabular py-1 text-right">{r.other}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableView>
    </ChartCard>
  );
}

export function CostChart({ points, bucket, dimmed }: { points: SeriesPoint[]; bucket: Bucket; dimmed?: boolean }) {
  const t = useTranslations("analytics.charts");
  const locale = localeTag(useLocale());
  const rows = points.map((p) => ({ t: p.t, cost: Number(p.cost_usd), credits: Number(p.credits) }));
  return (
    <ChartCard title={t("cost")} description={t("costDescription")} dimmed={dimmed}>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            {xAxis(bucket, locale)}
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={76} tickFormatter={(v: number) => formatUsd(v, locale)} />
            <Tooltip
              cursor={{ fill: "var(--muted)" }}
              content={(props) => <SeriesTooltip {...props} bucket={bucket} format={(v) => formatUsd(v, locale)} />}
            />
            <Bar isAnimationActive={false} dataKey="cost" name={t("cost")} fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={24} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableView summary={t("showTable")}>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-fg-subtle">
              <th className="py-1 pr-3 font-medium">{t("time")}</th>
              <th className="py-1 pr-3 text-right font-medium">{t("cost")}</th>
              <th className="py-1 text-right font-medium">{t("credits")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.t} className="border-t border-border">
                <td className="py-1 pr-3">{bucketLabel(r.t, bucket, locale, true)}</td>
                <td className="tabular py-1 pr-3 text-right">{formatUsd(r.cost, locale)}</td>
                <td className="tabular py-1 text-right">{formatNumber(r.credits, locale, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableView>
    </ChartCard>
  );
}

export function LatencyChart({ points, bucket, dimmed }: { points: SeriesPoint[]; bucket: Bucket; dimmed?: boolean }) {
  const t = useTranslations("analytics.charts");
  const locale = localeTag(useLocale());
  const rows = points.map((p) => ({ t: p.t, p50: p.p50_ms, p95: p.p95_ms }));
  const dot = { r: 4, stroke: "var(--surface)", strokeWidth: 2 };
  return (
    <ChartCard title={t("latency")} description={t("latencyDescription")} dimmed={dimmed}>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            {xAxis(bucket, locale)}
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={60} tickFormatter={(v: number) => formatDuration(v)} />
            <Tooltip
              cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
              content={(props) => <SeriesTooltip {...props} bucket={bucket} format={(v) => formatDuration(v)} />}
            />
            <Legend verticalAlign="top" align="right" iconType="plainline" iconSize={12} itemSorter={null} formatter={legendText} wrapperStyle={LEGEND_STYLE} />
            <Line isAnimationActive={false} type="monotone" dataKey="p50" name={t("p50")} stroke="var(--series-1)" strokeWidth={2} dot={false} activeDot={dot} connectNulls={false} strokeLinecap="round" />
            <Line isAnimationActive={false} type="monotone" dataKey="p95" name={t("p95")} stroke="var(--series-2)" strokeWidth={2} dot={false} activeDot={dot} connectNulls={false} strokeLinecap="round" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <TableView summary={t("showTable")}>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-fg-subtle">
              <th className="py-1 pr-3 font-medium">{t("time")}</th>
              <th className="py-1 pr-3 text-right font-medium">{t("p50")}</th>
              <th className="py-1 text-right font-medium">{t("p95")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.t} className="border-t border-border">
                <td className="py-1 pr-3">{bucketLabel(r.t, bucket, locale, true)}</td>
                <td className="tabular py-1 pr-3 text-right">{formatDuration(r.p50)}</td>
                <td className="tabular py-1 text-right">{formatDuration(r.p95)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableView>
    </ChartCard>
  );
}

/** Single-series value chart for custom metrics (columns for additive aggregates, a line otherwise). */
export function MetricValuesChart({
  points,
  bucket,
  format,
  name,
  additive,
}: {
  points: { t: string; value: number | null }[];
  bucket: Bucket;
  format: (value: number) => string;
  name: string;
  additive: boolean;
}) {
  const locale = localeTag(useLocale());
  return (
    <div className={cn("h-48", VIZ)}>
      <ResponsiveContainer width="100%" height="100%">
        {additive ? (
          <BarChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            {xAxis(bucket, locale)}
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={72} tickFormatter={(v: number) => format(v)} />
            <Tooltip cursor={{ fill: "var(--muted)" }} content={(props) => <SeriesTooltip {...props} bucket={bucket} format={format} />} />
            <Bar isAnimationActive={false} dataKey="value" name={name} fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={24} />
          </BarChart>
        ) : (
          <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            {xAxis(bucket, locale)}
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={72} tickFormatter={(v: number) => format(v)} />
            <Tooltip cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }} content={(props) => <SeriesTooltip {...props} bucket={bucket} format={format} />} />
            <Line isAnimationActive={false} type="monotone" dataKey="value" name={name} stroke="var(--series-1)" strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} connectNulls={false} />
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

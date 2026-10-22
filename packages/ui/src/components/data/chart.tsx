"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  type TooltipContentProps,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "../../lib/cn";
import { Skeleton } from "../skeleton";
import { DataStatus, type DataStateLabels } from "./data-state";
import { type DataRow, columnsOf, formatValue, humanize, isNumericColumn, toNumber } from "./format";

export type ChartKind = "bar" | "line" | "pie" | "area";
export type ChartValueFormat = "number" | "currency" | "percent";

export interface DataChartLabels extends DataStateLabels {
  table: string;
  other: string;
}

/**
 * Validated categorical palette (fixed order, never cycled), stepped separately for the dark surface.
 * Series colors identify marks only; every text uses the text tokens.
 */
const VIZ =
  "[--series-1:#2a78d6] [--series-2:#eb6834] [--series-3:#1baf7a] [--series-4:#eda100] [--series-5:#e87ba4] [--series-6:#008300] [--series-7:#6250d6] [--series-8:#e34948] " +
  "dark:[--series-1:#3987e5] dark:[--series-2:#d95926] dark:[--series-3:#199e70] dark:[--series-4:#c98500] dark:[--series-5:#d55181] dark:[--series-6:#008300] dark:[--series-7:#9085e9] dark:[--series-8:#e66767]";
const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);
const AXIS = { fontSize: 12, fill: "var(--fg-subtle)" } as const;
const MAX_SLICES = 8;

function compact(value: number, locale: string, format: ChartValueFormat, currency: string): string {
  if (format === "percent") return formatValue(value, "percent", { locale });
  const big = Math.abs(value) >= 1000;
  const opts: Intl.NumberFormatOptions = {
    notation: big ? "compact" : "standard",
    maximumFractionDigits: big ? 1 : Number.isInteger(value) ? 0 : 2,
    minimumFractionDigits: 0,
  };
  if (format === "currency") Object.assign(opts, { style: "currency", currency });
  return new Intl.NumberFormat(locale, opts).format(value);
}

function TooltipBox({
  active,
  payload,
  label,
  format,
}: TooltipContentProps & { format: (v: unknown) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 text-xs shadow-lg">
      {label !== undefined && label !== "" ? <p className="mb-1 font-medium text-fg">{String(label)}</p> : null}
      {payload.map((p, i) => (
        <p key={`${String(p.dataKey)}-${i}`} className="flex items-center gap-2 text-fg-muted">
          <span aria-hidden className="inline-block size-2 rounded-sm" style={{ background: p.color ?? p.payload?.fill }} />
          <span>{p.name}</span>
          <span className="tabular ml-auto pl-3 font-medium text-fg">{format(p.value)}</span>
        </p>
      ))}
    </div>
  );
}

export interface DataChartProps {
  rows: DataRow[];
  kind?: ChartKind;
  x?: string | null;
  y?: string[];
  stacked?: boolean;
  format?: ChartValueFormat;
  currency?: string;
  legend?: boolean;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  labels: DataChartLabels;
  locale?: string;
  title?: string;
  className?: string;
}

/** Bar, line, area or pie chart over rows (x column + numeric series), with tooltip and a table view. */
export function DataChart({
  rows,
  kind = "bar",
  x,
  y,
  stacked = false,
  format = "number",
  currency = "EUR",
  legend = true,
  loading,
  error,
  onRetry,
  labels,
  locale = "es-ES",
  title,
  className,
}: DataChartProps) {
  const columns = React.useMemo(() => columnsOf(rows), [rows]);
  const xKey = x || columns[0] || "";
  const series = React.useMemo(() => {
    if (y && y.length > 0) return y.slice(0, SERIES.length);
    return columns.filter((c) => c !== xKey && isNumericColumn(rows, c)).slice(0, SERIES.length);
  }, [y, columns, rows, xKey]);
  const data = React.useMemo(
    () =>
      rows.map((r) => {
        const out: Record<string, unknown> = { [xKey]: r[xKey] === null || r[xKey] === undefined ? "—" : String(r[xKey]) };
        for (const s of series) out[s] = toNumber(r[s]);
        return out;
      }),
    [rows, series, xKey],
  );
  const pieData = React.useMemo(() => {
    const key = series[0];
    if (kind !== "pie" || !key) return [];
    const items = data
      .map((d) => ({ name: String(d[xKey]), value: Number(d[key] ?? 0) }))
      .filter((d) => d.value > 0)
      .sort((a, b) => b.value - a.value);
    if (items.length <= MAX_SLICES) return items;
    const head = items.slice(0, MAX_SLICES - 1);
    const rest = items.slice(MAX_SLICES - 1).reduce((acc, d) => acc + d.value, 0);
    return [...head, { name: labels.other, value: rest }];
  }, [data, kind, series, xKey, labels.other]);

  const valueText = (v: unknown) => {
    const n = toNumber(v);
    return n === null ? "—" : formatValue(n, format, { locale, currency });
  };
  const tick = (v: number) => compact(v, locale, format, currency);
  const showLegend = legend && (kind === "pie" ? pieData.length > 1 : series.length > 1);
  const empty = !loading && !error && (rows.length === 0 || series.length === 0);

  let chart: React.ReactElement;
  if (kind === "pie") {
    chart = (
      <PieChart>
        <Tooltip content={(p) => <TooltipBox {...p} format={valueText} />} />
        <Pie data={pieData} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="85%" paddingAngle={1} stroke="var(--surface)" strokeWidth={2} isAnimationActive={false}>
          {pieData.map((d, i) => (
            <Cell key={d.name} fill={SERIES[i % SERIES.length]} />
          ))}
        </Pie>
        {showLegend ? <Legend iconType="square" iconSize={8} wrapperStyle={{ fontSize: 12, color: "var(--fg-muted)" }} /> : null}
      </PieChart>
    );
  } else {
    const common = {
      data,
      margin: { top: 8, right: 8, bottom: 0, left: 0 },
    };
    const axes = (
      <>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--border)" }} minTickGap={12} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} tickFormatter={tick} width={56} />
        <Tooltip
          cursor={kind === "bar" ? { fill: "var(--subtle)" } : { stroke: "var(--border-strong)" }}
          content={(p) => <TooltipBox {...p} format={valueText} />}
        />
        {showLegend ? <Legend iconType="square" iconSize={8} wrapperStyle={{ fontSize: 12, color: "var(--fg-muted)" }} /> : null}
      </>
    );
    if (kind === "line") {
      chart = (
        <LineChart {...common}>
          {axes}
          {series.map((s, i) => (
            <Line key={s} type="monotone" dataKey={s} name={humanize(s)} stroke={SERIES[i]} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} isAnimationActive={false} />
          ))}
        </LineChart>
      );
    } else if (kind === "area") {
      chart = (
        <AreaChart {...common}>
          {axes}
          {series.map((s, i) => (
            <Area key={s} type="monotone" dataKey={s} name={humanize(s)} stroke={SERIES[i]} strokeWidth={2} fill={SERIES[i]} fillOpacity={0.1} stackId={stacked ? "stack" : undefined} isAnimationActive={false} />
          ))}
        </AreaChart>
      );
    } else {
      chart = (
        <BarChart {...common} barGap={2} barCategoryGap="20%">
          {axes}
          {series.map((s, i) => (
            <Bar
              key={s}
              dataKey={s}
              name={humanize(s)}
              fill={SERIES[i]}
              maxBarSize={24}
              radius={stacked && i < series.length - 1 ? 0 : [4, 4, 0, 0]}
              stackId={stacked ? "stack" : undefined}
              stroke={stacked ? "var(--surface)" : undefined}
              strokeWidth={stacked ? 2 : 0}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      );
    }
  }

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col", VIZ, className)}>
      <DataStatus
        loading={loading}
        error={error}
        empty={empty}
        labels={labels}
        onRetry={onRetry}
        skeleton={<Skeleton className="h-full min-h-32 w-full" />}
      >
        <div className="min-h-32 flex-1" role="img" aria-label={title}>
          <ResponsiveContainer width="100%" height="100%">
            {chart}
          </ResponsiveContainer>
        </div>
        <details className="mt-1 text-xs">
          <summary className="cursor-pointer text-fg-muted hover:text-fg">{labels.table}</summary>
          <div className="mt-1 max-h-40 overflow-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-fg-subtle">
                  <th scope="col" className="py-0.5 pr-3 font-medium">
                    {humanize(xKey)}
                  </th>
                  {series.map((s) => (
                    <th key={s} scope="col" className="py-0.5 pr-3 text-right font-medium">
                      {humanize(s)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.map((d, i) => (
                  <tr key={i} className="text-fg">
                    <td className="py-0.5 pr-3">{String(d[xKey])}</td>
                    {series.map((s) => (
                      <td key={s} className="tabular py-0.5 pr-3 text-right">
                        {valueText(d[s])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </DataStatus>
    </div>
  );
}

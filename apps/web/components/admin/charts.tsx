"use client";

import { cn } from "@messer/ui";
import { useLocale, useTranslations } from "next-intl";
import type * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  type TooltipContentProps,
  XAxis,
  YAxis,
} from "recharts";

import { formatDate, formatNumber, formatUsd, localeTag } from "@/lib/format";

import type { BusinessMetrics, MonthPoint } from "./types";

/**
 * Chart colors: slots 1–2 of the validated categorical palette (blue, orange), stepped separately for the
 * dark surface. Text always uses the text tokens; colors only identify series.
 */
const VIZ = "[--series-1:#2a78d6] [--series-2:#eb6834] dark:[--series-1:#3987e5] dark:[--series-2:#d95926]";
const AXIS = { fontSize: 12, fill: "var(--fg-subtle)" } as const;

function ChartTooltip({
  active,
  payload,
  label,
  format,
  labelFormat,
  extra,
}: TooltipContentProps & {
  format: (v: number) => string;
  labelFormat: (v: string) => string;
  extra?: (label: string) => React.ReactNode;
}) {
  if (!active || !payload?.length) return null;
  const key = String(label ?? "");
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-medium text-fg">{labelFormat(key)}</p>
      {payload.map((p) => (
        <p key={String(p.dataKey)} className="flex items-center gap-2 text-fg-muted">
          <span aria-hidden className="inline-block size-2 rounded-sm" style={{ background: p.color }} />
          <span>{p.name}</span>
          <span className="tabular ml-auto pl-3 font-medium text-fg">{format(Number(p.value))}</span>
        </p>
      ))}
      {extra ? extra(key) : null}
    </div>
  );
}

function TableView({ summary, children }: { summary: string; children: React.ReactNode }) {
  return (
    <details className="mt-2 text-sm">
      <summary className="cursor-pointer text-xs text-fg-muted hover:text-fg">{summary}</summary>
      <div className="mt-2 overflow-x-auto">{children}</div>
    </details>
  );
}

export function SignupsChart({ data }: { data: BusinessMetrics["signups"] }) {
  const t = useTranslations("admin");
  const locale = localeTag(useLocale());
  const weekLabel = (iso: string) => formatDate(iso, locale);
  return (
    <div className={VIZ}>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis
              dataKey="week_start"
              tickFormatter={(v: string) => new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(new Date(v))}
              tick={AXIS}
              tickLine={false}
              axisLine={{ stroke: "var(--border)" }}
              interval="preserveStartEnd"
            />
            <YAxis allowDecimals={false} tick={AXIS} tickLine={false} axisLine={false} width={40} />
            <Tooltip
              cursor={{ fill: "var(--muted)" }}
              content={(props) => (
                <ChartTooltip {...props} format={(v) => formatNumber(v, locale)} labelFormat={(v) => t("metrics.weekOf", { date: weekLabel(v) })} />
              )}
            />
            <Bar dataKey="users" name={t("metrics.signupsUsers")} fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={28} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableView summary={t("metrics.showTable")}>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-fg-subtle">
              <th className="py-1 pr-3 font-medium">{t("metrics.week")}</th>
              <th className="py-1 pr-3 text-right font-medium">{t("metrics.signupsUsers")}</th>
              <th className="py-1 text-right font-medium">{t("metrics.signupsOrgs")}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((w) => (
              <tr key={w.week_start} className="border-t border-border">
                <td className="py-1 pr-3">{weekLabel(w.week_start)}</td>
                <td className="tabular py-1 pr-3 text-right">{w.users}</td>
                <td className="tabular py-1 text-right">{w.orgs}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableView>
    </div>
  );
}

export function CostRevenueChart({ data }: { data: MonthPoint[] }) {
  const t = useTranslations("admin");
  const locale = localeTag(useLocale());
  const monthLabel = (key: string) =>
    new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" }).format(new Date(`${key}-01T00:00:00Z`));
  const rows = data.map((m) => ({
    month: m.month,
    cost: Number(m.ai_cost_usd),
    revenue: Number(m.credits_revenue_usd),
    margin: Number(m.margin_usd),
  }));
  const marginFor = (key: string) => rows.find((r) => r.month === key)?.margin ?? 0;
  return (
    <div className={VIZ}>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="month" tickFormatter={monthLabel} tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--border)" }} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => formatUsd(v, locale)} />
            <Tooltip
              cursor={{ fill: "var(--muted)" }}
              content={(props) => (
                <ChartTooltip
                  {...props}
                  format={(v) => formatUsd(v, locale)}
                  labelFormat={monthLabel}
                  extra={(key) => (
                    <p className="mt-1 flex justify-between gap-3 border-t border-border pt-1 text-fg-muted">
                      <span>{t("metrics.margin")}</span>
                      <span className="tabular font-medium text-fg">{formatUsd(marginFor(key), locale)}</span>
                    </p>
                  )}
                />
              )}
            />
            <Legend
              verticalAlign="top"
              align="right"
              iconType="square"
              iconSize={8}
              wrapperStyle={{ fontSize: 12, color: "var(--fg-muted)", paddingBottom: 4 }}
            />
            <Bar dataKey="cost" name={t("metrics.aiCost")} fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={24} />
            <Bar dataKey="revenue" name={t("metrics.creditsRevenue")} fill="var(--series-2)" radius={[4, 4, 0, 0]} maxBarSize={24} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableView summary={t("metrics.showTable")}>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-fg-subtle">
              <th className="py-1 pr-3 font-medium">{t("metrics.month")}</th>
              <th className="py-1 pr-3 text-right font-medium">{t("metrics.aiCost")}</th>
              <th className="py-1 pr-3 text-right font-medium">{t("metrics.creditsRevenue")}</th>
              <th className="py-1 pr-3 text-right font-medium">{t("metrics.margin")}</th>
              <th className="py-1 text-right font-medium">{t("metrics.billedRevenue")}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((m) => (
              <tr key={m.month} className="border-t border-border">
                <td className="py-1 pr-3">{monthLabel(m.month)}</td>
                <td className="tabular py-1 pr-3 text-right">{formatUsd(m.ai_cost_usd, locale)}</td>
                <td className="tabular py-1 pr-3 text-right">{formatUsd(m.credits_revenue_usd, locale)}</td>
                <td className="tabular py-1 pr-3 text-right">{formatUsd(m.margin_usd, locale)}</td>
                <td className="tabular py-1 text-right">
                  {new Intl.NumberFormat(locale, { style: "currency", currency: "EUR" }).format(Number(m.billed_revenue_eur))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableView>
    </div>
  );
}

export function FunnelBars({ steps }: { steps: BusinessMetrics["activation_funnel"] }) {
  const t = useTranslations("admin");
  const locale = localeTag(useLocale());
  const top = steps[0]?.orgs ?? 0;
  return (
    <ol className={cn("flex flex-col gap-2", VIZ)}>
      {steps.map((s) => {
        const pct = top > 0 ? Math.round((s.orgs / top) * 100) : 0;
        return (
          <li key={s.step} className="grid grid-cols-[9rem_1fr_5.5rem] items-center gap-3 text-sm">
            <span className="text-fg-muted">{t(`metrics.funnel.${s.step}`)}</span>
            <span className="h-2 rounded-r-[4px] bg-muted" aria-hidden>
              <span
                className="block h-full rounded-r-[4px] bg-[var(--series-1)]"
                style={{ width: `${Math.max(pct, s.orgs > 0 ? 2 : 0)}%` }}
              />
            </span>
            <span className="tabular text-right">
              {formatNumber(s.orgs, locale)} <span className="text-xs text-fg-subtle">· {pct}%</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

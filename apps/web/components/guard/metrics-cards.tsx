"use client";

import { Alert, Badge, Card, CardBody, CardHeader, ErrorState, Select, Skeleton, Stat } from "@messer/ui";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatDate, formatNumber, formatUsd, localeTag } from "@/lib/format";

import { useGuardMetrics } from "./hooks";
import type { GuardMetrics } from "./types";

/** Categorical series colors (validated palette slots, separate steps for the dark surface). */
const VIZ =
  "[--series-1:#2a78d6] [--series-2:#eb6834] dark:[--series-1:#3987e5] dark:[--series-2:#d95926]";
const AXIS = { fontSize: 12, fill: "var(--fg-subtle)" } as const;
const RANGES = [7, 30, 90] as const;

function percent(value: number | null, locale: string): string {
  if (value === null) return "—";
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(value);
}

function DailyChart({ metrics }: { metrics: GuardMetrics }) {
  const t = useTranslations("guard.metrics");
  const locale = localeTag(useLocale());
  const data = metrics.daily.map((d) => ({
    day: d.day,
    onPath: d.on_path,
    offPath: Math.max(0, d.turns - d.on_path),
    blocked: d.blocked,
  }));
  return (
    <div className={`h-44 ${VIZ}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="day"
            tick={AXIS}
            tickLine={false}
            axisLine={false}
            tickFormatter={(d: string) => formatDate(`${d}T12:00:00Z`, locale).replace(/\s\d{4}$/, "")}
          />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} width={40} />
          <Tooltip
            cursor={{ fill: "var(--subtle)" }}
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelFormatter={(d) => formatDate(`${String(d)}T12:00:00Z`, locale)}
            formatter={(value, name) => [formatNumber(Number(value), locale), String(name)]}
          />
          <Bar dataKey="onPath" name={t("chartOnPath")} stackId="turns" fill="var(--series-1)" radius={[0, 0, 2, 2]} />
          <Bar dataKey="offPath" name={t("chartOffPath")} stackId="turns" fill="var(--series-2)" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MetricsCards({ projectId, member }: { projectId: string; member: string }) {
  const t = useTranslations("guard.metrics");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const [days, setDays] = React.useState<number>(30);
  const metrics = useGuardMetrics(projectId, member, days);
  const m = metrics.data;

  return (
    <Card>
      <CardHeader
        title={t("title")}
        description={t("range", { days })}
        actions={
          <div className="w-28">
            <Select
              aria-label={t("title")}
              value={String(days)}
              onValueChange={(v) => setDays(Number(v))}
              options={RANGES.map((r) => ({ value: String(r), label: t(`ranges.${r}`) }))}
            />
          </div>
        }
      />
      <CardBody className="flex flex-col gap-4">
        {metrics.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        ) : metrics.error || !m ? (
          <ErrorState
            title={tc("errorTitle")}
            description={tc("errorGeneric")}
            onRetry={() => void metrics.refetch()}
            retryLabel={tc("retry")}
          />
        ) : m.turns === 0 ? (
          <p className="text-sm text-fg-muted">{t("noData")}</p>
        ) : (
          <>
            {m.demo ? <Alert tone="info">{t("demo")}</Alert> : null}
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Stat
                label={t("onPath")}
                value={percent(m.on_path_share, locale)}
                hint={t("onPathHint", { onPath: m.on_path_turns, turns: m.turns })}
              />
              <Stat
                label={t("costPerRun")}
                value={m.cost.per_run_guarded_usd !== null ? formatUsd(m.cost.per_run_guarded_usd, locale) : "—"}
                hint={
                  m.cost.per_run_baseline_usd !== null
                    ? t("costPerRunHint", { baseline: formatUsd(m.cost.per_run_baseline_usd, locale) })
                    : undefined
                }
              />
              <Stat
                label={t("savings")}
                value={m.cost.savings_pct !== null ? `${formatNumber(m.cost.savings_pct, locale, 1)} %` : "—"}
                tone={m.cost.savings_pct !== null && m.cost.savings_pct > 0 ? "success" : m.cost.savings_pct !== null && m.cost.savings_pct < 0 ? "warning" : undefined}
                hint={t("savingsHint")}
              />
              <Stat
                label={t("blocked")}
                value={formatNumber(m.blocked_actions, locale)}
                tone={m.blocked_actions > 0 ? "danger" : undefined}
                hint={t("blockedHint", { runs: m.runs })}
              />
            </div>
            <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
              <div className="min-w-0">
                <p className="mb-2 text-xs font-medium text-fg-muted">{t("chartTitle")}</p>
                <DailyChart metrics={m} />
              </div>
              <div className="flex flex-col gap-2">
                <p className="text-xs font-medium text-fg-muted">{t("routes")}</p>
                <ul className="flex flex-col gap-1.5 text-sm">
                  {Object.entries(m.routes)
                    .sort((a, b) => b[1] - a[1])
                    .map(([route, n]) => (
                      <li key={route} className="flex items-center justify-between gap-2">
                        <span className="text-fg-muted">{t.has(`routeLabels.${route}`) ? t(`routeLabels.${route}`) : route}</span>
                        <span className="tabular font-medium">{formatNumber(n, locale)}</span>
                      </li>
                    ))}
                </ul>
                <p className="mt-auto text-xs text-fg-subtle">
                  {t("overhead", { value: formatUsd(m.cost.overhead_usd, locale) })}
                </p>
                {m.errors > 0 ? <Badge tone="danger">{t("issues", { errors: m.errors })}</Badge> : null}
              </div>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

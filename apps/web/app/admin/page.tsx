"use client";

import { Badge, Card, CardBody, CardHeader, EmptyState, ErrorState, PageHeader, SkeletonRows, Stat } from "@messer/ui";
import { useQuery } from "@tanstack/react-query";
import { LineChart } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { CostRevenueChart, FunnelBars, SignupsChart } from "@/components/admin/charts";
import { ADMIN_KEY, type BusinessMetrics } from "@/components/admin/types";
import { http } from "@/lib/api";
import { formatDate, formatEur, formatNumber, formatUsd, localeTag } from "@/lib/format";

function pct(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1).replace(/\.0$/, "")}%`;
}

export default function AdminMetricsPage() {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const metrics = useQuery({
    queryKey: [...ADMIN_KEY, "metrics"],
    queryFn: () => http.get<BusinessMetrics>("/admin/metrics", { weeks: 12, months: 6 }),
  });

  if (metrics.isLoading) return <SkeletonRows rows={10} />;
  if (metrics.error || !metrics.data) {
    return <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void metrics.refetch()} />;
  }
  const m = metrics.data;
  const current = m.current_month;
  const maxPlanMrr = Math.max(1, ...m.mrr_by_plan.map((p) => Number(p.mrr_eur)));

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {t("metrics.title")}
            {m.test_mode ? <Badge tone="warning">{t("metrics.testMode")}</Badge> : null}
          </span>
        }
        description={t("metrics.description", { date: formatDate(m.generated_at, locale, true) })}
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("metrics.mrr")} value={formatEur(m.mrr_eur, locale, 2)} hint={t("metrics.arr", { value: formatEur(m.arr_eur, locale) })} />
        <Stat
          label={t("metrics.paidSubscriptions")}
          value={formatNumber(m.paid_subscriptions, locale)}
          hint={t("metrics.pastDueHint", { count: m.past_due })}
          tone={m.past_due > 0 ? "warning" : undefined}
        />
        <Stat
          label={t("metrics.conversion")}
          value={pct(m.trial_conversion.rate)}
          hint={t("metrics.conversionHint", {
            converted: m.trial_conversion.converted,
            started: m.trial_conversion.trials_started,
            days: m.trial_conversion.window_days,
          })}
        />
        <Stat
          label={t("metrics.churn")}
          value={pct(m.churn.rate)}
          hint={t("metrics.churnHint", { canceled: m.churn.canceled, days: m.churn.window_days })}
          tone={m.churn.rate !== null && m.churn.rate > 0.05 ? "danger" : undefined}
        />
        <Stat label={t("metrics.trialsActive")} value={formatNumber(m.trials_active, locale)} />
        <Stat label={t("metrics.totals")} value={formatNumber(m.totals.orgs, locale)} hint={t("metrics.totalsHint", { users: m.totals.users })} />
        <Stat label={t("metrics.aiCostMonth")} value={current ? formatUsd(current.ai_cost_usd, locale) : "—"} />
        <Stat
          label={t("metrics.marginMonth")}
          value={current ? formatUsd(current.margin_usd, locale) : "—"}
          hint={current ? t("metrics.revenueHint", { value: formatUsd(current.credits_revenue_usd, locale) }) : undefined}
          tone={current && Number(current.margin_usd) < 0 ? "danger" : undefined}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("metrics.costVsRevenue")} description={t("metrics.costVsRevenueHint")} />
          <CardBody>
            {m.ai_cost_vs_revenue.every((p) => Number(p.ai_cost_usd) === 0 && Number(p.credits_revenue_usd) === 0) ? (
              <EmptyState icon={<LineChart />} title={t("metrics.noUsageTitle")} description={t("metrics.noUsage")} />
            ) : (
              <CostRevenueChart data={m.ai_cost_vs_revenue} />
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t("metrics.signups")} description={t("metrics.signupsHint")} />
          <CardBody>
            <SignupsChart data={m.signups} />
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("metrics.mrrByPlan")} />
          <CardBody>
            {m.mrr_by_plan.length === 0 ? (
              <p className="text-sm text-fg-subtle">{t("metrics.noPaid")}</p>
            ) : (
              <ul className="flex flex-col gap-2.5 [--series-1:#2a78d6] dark:[--series-1:#3987e5]">
                {m.mrr_by_plan.map((p) => (
                  <li key={p.plan_id} className="grid grid-cols-[7rem_1fr_7rem] items-center gap-3 text-sm">
                    <span>
                      {p.plan_name}
                      <span className="block text-xs text-fg-subtle">{t("metrics.subscriptions", { count: p.subscriptions })}</span>
                    </span>
                    <span className="h-2 rounded-r-[4px] bg-muted" aria-hidden>
                      <span
                        className="block h-full rounded-r-[4px] bg-[var(--series-1)]"
                        style={{ width: `${(Number(p.mrr_eur) / maxPlanMrr) * 100}%` }}
                      />
                    </span>
                    <span className="tabular text-right font-medium">{formatEur(p.mrr_eur, locale, 2)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t("metrics.funnelTitle")} description={t("metrics.funnelHint")} />
          <CardBody>
            <FunnelBars steps={m.activation_funnel} />
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

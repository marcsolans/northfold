"use client";

import { Button, EmptyState, ErrorState, Skeleton } from "@messer/ui";
import { BarChart3 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import type * as React from "react";

import { BreakdownCard, CsvButton } from "./breakdown";
import { CostChart, LatencyChart, RunsChart } from "./charts";
import { FeedbackCard } from "./feedback";
import { AnalyticsFilterBar, useAnalyticsFilters } from "./filters";
import { KpiGrid, KpiGridSkeleton } from "./kpis";
import { csvHref, useFilterOptions, useOverview, useTimeseries } from "./queries";
import type { GroupBy } from "./types";

const ORG_GROUPS: GroupBy[] = ["project", "agent", "channel", "user", "model", "environment"];
const PROJECT_GROUPS: GroupBy[] = ["agent", "channel", "user", "model", "environment"];

/** Organization (no ``projectId``) or project analytics: filters, KPIs, charts, breakdowns and feedback. */
export function AnalyticsDashboard({ projectId, children }: { projectId?: string; children?: React.ReactNode }) {
  const t = useTranslations("analytics");
  const tc = useTranslations("common");
  const filters = useAnalyticsFilters(projectId);
  const { query, valid } = filters;
  const options = useFilterOptions(query, valid);
  const overview = useOverview(query, valid);
  const series = useTimeseries(query, valid);
  const empty = overview.data !== undefined && overview.data.kpis.runs === 0 && overview.data.previous.runs === 0;
  const refreshing = overview.isFetching || series.isFetching;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        <AnalyticsFilterBar filters={filters} options={options.data} showProject={!projectId} refreshing={refreshing} />
        <div className="flex flex-wrap justify-end gap-2">
          <CsvButton href={csvHref("overview", query)} label={t("csvOverview")} />
          <CsvButton href={csvHref("timeseries", query)} label={t("csvTimeseries")} />
        </div>
      </div>

      {overview.error ? (
        <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void overview.refetch()} retryLabel={tc("retry")} />
      ) : overview.data ? (
        <div className={overview.isPlaceholderData ? "opacity-60 transition-opacity" : "transition-opacity"}>
          <KpiGrid data={overview.data} />
        </div>
      ) : (
        <KpiGridSkeleton />
      )}

      {empty ? (
        <EmptyState
          icon={<BarChart3 />}
          title={filters.hasFilters ? t("empty.filteredTitle") : t("empty.title")}
          description={filters.hasFilters ? t("empty.filteredDescription") : t("empty.description")}
          action={
            !filters.hasFilters ? (
              <Button asChild variant="secondary">
                <Link href={projectId ? `/app/projects/${projectId}/agents` : "/app/projects"}>{t("empty.action")}</Link>
              </Button>
            ) : null
          }
        />
      ) : (
        <>
          {series.error ? (
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void series.refetch()} retryLabel={tc("retry")} />
          ) : series.data ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <RunsChart points={series.data.points} bucket={series.data.bucket} dimmed={series.isPlaceholderData} />
              <CostChart points={series.data.points} bucket={series.data.bucket} dimmed={series.isPlaceholderData} />
              <LatencyChart points={series.data.points} bucket={series.data.bucket} dimmed={series.isPlaceholderData} />
              <FeedbackCard query={query} enabled={valid} />
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2" aria-hidden>
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-80" />
              ))}
            </div>
          )}
          <BreakdownCard query={query} enabled={valid} groups={projectId ? PROJECT_GROUPS : ORG_GROUPS} linkProjects={!projectId} />
        </>
      )}
      {children}
    </div>
  );
}

"use client";

/** TanStack Query hooks for the governance API. Refetches keep the previous render (no skeleton flash). */

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiUrl, http } from "@/lib/api";

import type {
  Alarm,
  AlarmCatalog,
  AlarmEvent,
  Breakdown,
  CustomMetric,
  EvalComparison,
  FeedbackDetail,
  FilterOptions,
  GroupBy,
  ModelPolicy,
  Overview,
  SortKey,
  Timeseries,
} from "./types";

/** Query parameters shared by every analytics endpoint (the filter bar's slice). */
export interface AnalyticsQuery {
  since: string;
  until: string;
  tz: string;
  project_id?: string;
  environment?: string;
  channel?: string;
  workforce?: string;
}

type Params = Record<string, string | number | boolean | null | undefined>;

function params(q: AnalyticsQuery, extra: Params = {}): Params {
  return { ...q, ...extra };
}

export const analyticsKeys = {
  all: ["analytics"] as const,
  overview: (q: AnalyticsQuery) => ["analytics", "overview", q] as const,
  timeseries: (q: AnalyticsQuery) => ["analytics", "timeseries", q] as const,
  breakdown: (q: AnalyticsQuery, group: GroupBy, sort: SortKey) => ["analytics", "breakdown", q, group, sort] as const,
  feedback: (q: AnalyticsQuery) => ["analytics", "feedback", q] as const,
  filters: (q: AnalyticsQuery) => ["analytics", "filters", q] as const,
  metrics: ["metrics"] as const,
  alarms: ["alarms"] as const,
  alarmHistory: (id: string) => ["alarms", id, "history"] as const,
  alarmCatalog: ["alarms", "catalog"] as const,
  policy: ["model-policy"] as const,
  evals: (projectId: string, name: string) => ["analytics", "evals", projectId, name] as const,
};

export function useOverview(q: AnalyticsQuery, enabled = true) {
  return useQuery({
    queryKey: analyticsKeys.overview(q),
    queryFn: ({ signal }) => http.get<Overview>("/analytics/overview", params(q), signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useTimeseries(q: AnalyticsQuery, enabled = true) {
  return useQuery({
    queryKey: analyticsKeys.timeseries(q),
    queryFn: ({ signal }) => http.get<Timeseries>("/analytics/timeseries", params(q), signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useBreakdown(q: AnalyticsQuery, group: GroupBy, sort: SortKey, enabled = true) {
  return useQuery({
    queryKey: analyticsKeys.breakdown(q, group, sort),
    queryFn: ({ signal }) =>
      http.get<Breakdown>("/analytics/breakdown", params(q, { group_by: group, sort, limit: 100 }), signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useFeedback(q: AnalyticsQuery, enabled = true) {
  return useQuery({
    queryKey: analyticsKeys.feedback(q),
    queryFn: ({ signal }) => http.get<FeedbackDetail>("/analytics/feedback", params(q, { limit: 6 }), signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useFilterOptions(q: AnalyticsQuery, enabled = true) {
  return useQuery({
    queryKey: analyticsKeys.filters(q),
    queryFn: ({ signal }) => http.get<FilterOptions>("/analytics/filters", params(q), signal),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    enabled,
  });
}

export function useCustomMetrics() {
  return useQuery({ queryKey: analyticsKeys.metrics, queryFn: () => http.get<CustomMetric[]>("/metrics") });
}

export function useAlarms() {
  return useQuery({ queryKey: analyticsKeys.alarms, queryFn: () => http.get<Alarm[]>("/alarms") });
}

export function useAlarmCatalog() {
  return useQuery({ queryKey: analyticsKeys.alarmCatalog, queryFn: () => http.get<AlarmCatalog>("/alarms/metrics") });
}

export function useAlarmHistory(alarmId: string | null) {
  return useQuery({
    queryKey: analyticsKeys.alarmHistory(alarmId ?? ""),
    queryFn: () => http.get<AlarmEvent[]>(`/alarms/${alarmId}/history`, { limit: 100 }),
    enabled: Boolean(alarmId),
  });
}

export function useModelPolicy() {
  return useQuery({ queryKey: analyticsKeys.policy, queryFn: () => http.get<ModelPolicy>("/model-policy") });
}

export function useEvalComparison(projectId: string, name: string | null) {
  return useQuery({
    queryKey: analyticsKeys.evals(projectId, name ?? ""),
    queryFn: () =>
      http.get<EvalComparison>(`/projects/${projectId}/workforce/${encodeURIComponent(name ?? "")}/evals/compare`, {
        versions: 12,
      }),
    enabled: Boolean(name),
  });
}

export type ExportView = "overview" | "timeseries" | "breakdown" | "feedback";

/** Same-origin CSV link (cookies carry the session and the active organization). */
export function csvHref(view: ExportView, q: AnalyticsQuery, extra: Params = {}): string {
  return apiUrl("/analytics/export.csv", params(q, { view, ...extra }));
}

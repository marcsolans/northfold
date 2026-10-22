"use client";

import { Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Select, SkeletonRows } from "@messer/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Activity, FilterX, RefreshCw } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { dateInputToIso } from "@/lib/studio/format";
import { useMembers } from "@/lib/studio/hooks";
import { RUN_STATUSES, type RunPage } from "@/lib/studio/types";

import { useRunStatusLabel } from "./run-status-badge";
import { RunsTable, useChannelLabel } from "./runs-table";

const CHANNELS = ["studio", "api", "chat", "widget", "whatsapp", "slack", "teams", "email", "telegram", "phone", "voice", "webhook", "cron"];
const FILTER_KEYS = ["status", "workforce", "channel", "environment", "from", "to"] as const;
type FilterKey = (typeof FILTER_KEYS)[number];
const PAGE_SIZE = 50;

export function TracesList({ projectId }: { projectId: string }) {
  const t = useTranslations("traces");
  const tc = useTranslations("common");
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const statusLabel = useRunStatusLabel();
  const channelLabel = useChannelLabel();
  const members = useMembers(projectId);

  const filters = Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ""])) as Record<FilterKey, string>;
  const setFilter = (key: FilterKey, value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value && value !== "all") next.set(key, value);
    else next.delete(key);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };
  const anyFilter = FILTER_KEYS.some((k) => filters[k]);

  const query = {
    project_id: projectId,
    status: filters.status || undefined,
    workforce: filters.workforce || undefined,
    channel: filters.channel || undefined,
    environment: filters.environment || undefined,
    since: dateInputToIso(filters.from),
    until: dateInputToIso(filters.to, true),
  };

  const runs = useInfiniteQuery({
    queryKey: ["runs", "list", query],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => http.get<RunPage>("/runs", { ...query, cursor: pageParam, limit: PAGE_SIZE }, signal),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = runs.data?.pages.flatMap((p) => p.items) ?? [];
  const rangeInvalid = Boolean(filters.from && filters.to && filters.from > filters.to);

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 md:px-6">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button variant="secondary" onClick={() => void runs.refetch()} loading={runs.isRefetching && !runs.isFetchingNextPage}>
            <RefreshCw />
            {t("refresh")}
          </Button>
        }
      />
      <Card className="mb-4 p-3">
        <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6" onSubmit={(e) => e.preventDefault()} aria-label={t("filters.label")}>
          <Field label={t("filters.status")} htmlFor="f-status">
            <Select
              id="f-status"
              aria-label={t("filters.status")}
              value={filters.status || "all"}
              onValueChange={(v) => setFilter("status", v)}
              options={[{ value: "all", label: tc("all") }, ...RUN_STATUSES.map((s) => ({ value: s, label: statusLabel(s) }))]}
            />
          </Field>
          <Field label={t("filters.workforce")} htmlFor="f-workforce">
            <Select
              id="f-workforce"
              aria-label={t("filters.workforce")}
              value={filters.workforce || "all"}
              onValueChange={(v) => setFilter("workforce", v)}
              options={[
                { value: "all", label: tc("all") },
                ...(members.data ?? []).map((m) => ({ value: m.name, label: m.name })),
                ...(filters.workforce && !(members.data ?? []).some((m) => m.name === filters.workforce)
                  ? [{ value: filters.workforce, label: filters.workforce }]
                  : []),
              ]}
            />
          </Field>
          <Field label={t("filters.channel")} htmlFor="f-channel">
            <Select
              id="f-channel"
              aria-label={t("filters.channel")}
              value={filters.channel || "all"}
              onValueChange={(v) => setFilter("channel", v)}
              options={[
                { value: "all", label: tc("all") },
                ...[...new Set([...CHANNELS, ...(filters.channel ? [filters.channel] : [])])].map((c) => ({ value: c, label: channelLabel(c) })),
              ]}
            />
          </Field>
          <Field label={t("filters.environment")} htmlFor="f-env">
            <Select
              id="f-env"
              aria-label={t("filters.environment")}
              value={filters.environment || "all"}
              onValueChange={(v) => setFilter("environment", v)}
              options={[
                { value: "all", label: tc("all") },
                { value: "development", label: t("environments.development") },
                { value: "production", label: t("environments.production") },
              ]}
            />
          </Field>
          <Field label={t("filters.from")} htmlFor="f-from">
            <Input id="f-from" type="date" value={filters.from} max={filters.to || undefined} onChange={(e) => setFilter("from", e.target.value)} />
          </Field>
          <Field label={t("filters.to")} htmlFor="f-to" error={rangeInvalid ? t("filters.rangeInvalid") : undefined}>
            <Input id="f-to" type="date" value={filters.to} min={filters.from || undefined} aria-invalid={rangeInvalid || undefined} onChange={(e) => setFilter("to", e.target.value)} />
          </Field>
        </form>
        {anyFilter ? (
          <div className="mt-2 flex justify-end">
            <Button size="sm" variant="ghost" onClick={() => router.replace(pathname, { scroll: false })}>
              <FilterX />
              {t("filters.clear")}
            </Button>
          </div>
        ) : null}
      </Card>

      <Card>
        {runs.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={8} />
          </div>
        ) : runs.error ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void runs.refetch()} retryLabel={tc("retry")} />
          </div>
        ) : items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<Activity />}
              title={anyFilter ? t("empty.filteredTitle") : t("empty.title")}
              description={anyFilter ? t("empty.filteredDescription") : t("empty.description")}
            />
          </div>
        ) : (
          <>
            <RunsTable runs={items} />
            <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-xs text-fg-muted">
              <span className="tabular">{t("shown", { count: items.length })}</span>
              {runs.hasNextPage ? (
                <Button size="sm" variant="secondary" loading={runs.isFetchingNextPage} onClick={() => void runs.fetchNextPage()}>
                  {t("loadMore")}
                </Button>
              ) : (
                <span>{t("end")}</span>
              )}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

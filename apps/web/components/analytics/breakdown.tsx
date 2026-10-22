"use client";

import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Select,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Tabs,
  TabsList,
  TabsTrigger,
  cn,
} from "@messer/ui";
import { Download, Table2 } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { formatDuration, formatNumber, formatRelative, formatUsd, localeTag } from "@/lib/format";

import { compactNumber, formatRatio } from "./format";
import { type AnalyticsQuery, csvHref, useBreakdown } from "./queries";
import type { BreakdownRow, GroupBy, SortKey } from "./types";

const RUN_SORTS: SortKey[] = ["runs", "cost_usd", "errors", "error_rate", "p95_ms", "users"];

export function CsvButton({ href, label }: { href: string; label?: string }) {
  const t = useTranslations("analytics");
  return (
    <Button asChild variant="secondary" size="sm">
      <a href={href} download>
        <Download />
        {label ?? t("csv")}
      </a>
    </Button>
  );
}

function RunRows({ rows, group, linkProjects }: { rows: BreakdownRow[]; group: GroupBy; linkProjects: boolean }) {
  const t = useTranslations("analytics.breakdown");
  const tl = useTranslations("analytics");
  const locale = localeTag(useLocale());
  const label = (r: BreakdownRow) => {
    if (group === "environment") return tl.has(`environments.${r.key}`) ? tl(`environments.${r.key}`) : r.label;
    if (group === "channel") return tl.has(`channels.${r.key}`) ? tl(`channels.${r.key}`) : r.label;
    if (group === "user" && r.key === "anonymous") return t("anonymous");
    return r.label || "—";
  };
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t(`groups.${group}`)}</TH>
          {group === "agent" ? <TH className="hidden md:table-cell">{t("columns.project")}</TH> : null}
          <TH className="text-right">{t("columns.runs")}</TH>
          <TH className="text-right">{t("columns.successRate")}</TH>
          <TH className="hidden text-right sm:table-cell">{t("columns.errors")}</TH>
          <TH className="text-right">{t("columns.cost")}</TH>
          <TH className="hidden text-right lg:table-cell">{t("columns.credits")}</TH>
          {group !== "user" ? <TH className="hidden text-right lg:table-cell">{t("columns.users")}</TH> : null}
          <TH className="hidden text-right md:table-cell">{t("columns.p50")}</TH>
          <TH className="text-right">{t("columns.p95")}</TH>
          <TH className="hidden text-right xl:table-cell">{t("columns.lastRun")}</TH>
        </tr>
      </THead>
      <TBody>
        {rows.map((r) => (
          <TR key={r.key}>
            <TD className="max-w-[16rem] truncate font-medium">
              {group === "project" && linkProjects && r.project_id ? (
                <Link className="hover:underline" href={`/app/projects/${r.project_id}/analytics`}>
                  {label(r)}
                </Link>
              ) : (
                label(r)
              )}
            </TD>
            {group === "agent" ? <TD className="hidden text-fg-muted md:table-cell">{r.project_name ?? "—"}</TD> : null}
            <TD className="tabular text-right">{formatNumber(r.runs, locale)}</TD>
            <TD className="tabular text-right">{formatRatio(r.success_rate, locale)}</TD>
            <TD className={cn("tabular hidden text-right sm:table-cell", r.errors > 0 && "text-danger")}>{formatNumber(r.errors, locale)}</TD>
            <TD className="tabular text-right">{formatUsd(r.cost_usd, locale)}</TD>
            <TD className="tabular hidden text-right lg:table-cell">{formatNumber(Number(r.credits ?? 0), locale, 2)}</TD>
            {group !== "user" ? <TD className="tabular hidden text-right lg:table-cell">{formatNumber(r.users ?? 0, locale)}</TD> : null}
            <TD className="tabular hidden text-right md:table-cell">{formatDuration(r.p50_ms)}</TD>
            <TD className="tabular text-right">{formatDuration(r.p95_ms)}</TD>
            <TD className="hidden text-right text-fg-muted xl:table-cell">{r.last_run_at ? formatRelative(r.last_run_at, locale) : "—"}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function ModelRows({ rows }: { rows: BreakdownRow[] }) {
  const t = useTranslations("analytics.breakdown");
  const locale = localeTag(useLocale());
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t("groups.model")}</TH>
          <TH className="text-right">{t("columns.runs")}</TH>
          <TH className="text-right">{t("columns.calls")}</TH>
          <TH className="hidden text-right md:table-cell">{t("columns.inputTokens")}</TH>
          <TH className="hidden text-right md:table-cell">{t("columns.outputTokens")}</TH>
          <TH className="text-right">{t("columns.cost")}</TH>
          <TH className="hidden text-right sm:table-cell">{t("columns.p95")}</TH>
          <TH className="hidden text-right lg:table-cell">{t("columns.errors")}</TH>
        </tr>
      </THead>
      <TBody>
        {rows.map((r) => (
          <TR key={r.key}>
            <TD>
              <span className="font-medium">{r.label}</span>
              {r.label !== r.key ? <span className="block font-mono text-[11px] text-fg-subtle">{r.key}</span> : null}
            </TD>
            <TD className="tabular text-right">{formatNumber(r.runs, locale)}</TD>
            <TD className="tabular text-right">{formatNumber(r.calls ?? 0, locale)}</TD>
            <TD className="tabular hidden text-right md:table-cell">{compactNumber(r.input_tokens ?? 0, locale)}</TD>
            <TD className="tabular hidden text-right md:table-cell">{compactNumber(r.output_tokens ?? 0, locale)}</TD>
            <TD className="tabular text-right">{formatUsd(r.cost_usd, locale)}</TD>
            <TD className="tabular hidden text-right sm:table-cell">{formatDuration(r.p95_ms)}</TD>
            <TD className={cn("tabular hidden text-right lg:table-cell", r.errors > 0 && "text-danger")}>{formatNumber(r.errors, locale)}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function BreakdownCard({
  query,
  enabled,
  groups,
  linkProjects,
}: {
  query: AnalyticsQuery;
  enabled: boolean;
  groups: GroupBy[];
  linkProjects: boolean;
}) {
  const t = useTranslations("analytics.breakdown");
  const tc = useTranslations("common");
  const [group, setGroup] = React.useState<GroupBy>(groups[0] ?? "project");
  const [sort, setSort] = React.useState<SortKey>("runs");
  const data = useBreakdown(query, group, group === "model" ? "runs" : sort, enabled);
  const rows = data.data?.group_by === group ? data.data.rows : [];
  const loading = data.isLoading || (data.isFetching && data.data?.group_by !== group);
  const href = csvHref("breakdown", query, { group_by: group, sort });

  return (
    <Card className="min-w-0">
      <CardHeader
        title={t("title")}
        description={t("description")}
        actions={
          <>
            {group !== "model" ? (
              <div className="hidden w-40 sm:block">
                <Select
                  aria-label={t("sort")}
                  value={sort}
                  onValueChange={(v) => setSort(v as SortKey)}
                  options={RUN_SORTS.map((s) => ({ value: s, label: t(`sorts.${s}`) }))}
                />
              </div>
            ) : null}
            <CsvButton href={href} />
          </>
        }
      />
      <div className="border-b border-border px-4 pt-2">
        <Tabs value={group} onValueChange={(v) => setGroup(v as GroupBy)}>
          <TabsList aria-label={t("groupsLabel")}>
            {groups.map((g) => (
              <TabsTrigger key={g} value={g}>
                {t(`groups.${g}`)}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>
      <div className={cn("overflow-x-auto transition-opacity", data.isFetching && !loading && "opacity-60")}>
        {loading ? (
          <div className="p-4">
            <SkeletonRows rows={5} />
          </div>
        ) : data.error ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void data.refetch()} retryLabel={tc("retry")} />
          </div>
        ) : rows.length === 0 ? (
          <div className="p-4">
            <EmptyState icon={<Table2 />} title={t("emptyTitle")} description={t("emptyDescription")} />
          </div>
        ) : group === "model" ? (
          <ModelRows rows={rows} />
        ) : (
          <RunRows rows={rows} group={group} linkProjects={linkProjects} />
        )}
      </div>
    </Card>
  );
}

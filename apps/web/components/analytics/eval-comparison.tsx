"use client";

import { Card, CardHeader, EmptyState, ErrorState, Select, SkeletonRows, Tooltip, TooltipProvider, cn } from "@messer/ui";
import { FlaskConical } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { formatDate, localeTag } from "@/lib/format";
import { useMembers } from "@/lib/studio/hooks";

import { formatRatio } from "./format";
import { useEvalComparison } from "./queries";
import type { EvalVersion } from "./types";

function tone(rate: number): string {
  if (rate >= 1) return "bg-success-soft text-success";
  if (rate <= 0) return "bg-danger-soft text-danger";
  return "bg-warning-soft text-warning";
}

function useVersionLabel() {
  const t = useTranslations("analytics.evals");
  return (v: EvalVersion) => {
    if (v.number === null) return t("unversioned");
    return v.entity_type === "project" ? t("projectVersion", { number: v.number }) : t("version", { number: v.number });
  };
}

/** Pass rate per eval case across the versions of one agent or workflow (heatmap table). */
export function EvalComparisonCard({ projectId }: { projectId: string }) {
  const t = useTranslations("analytics.evals");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const members = useMembers(projectId);
  const [selected, setSelected] = React.useState<string | null>(null);
  const name = selected ?? members.data?.[0]?.name ?? null;
  const data = useEvalComparison(projectId, name);
  const versionLabel = useVersionLabel();

  const picker =
    members.data && members.data.length > 0 ? (
      <div className="w-56">
        <Select
          aria-label={t("member")}
          value={name ?? undefined}
          onValueChange={setSelected}
          options={members.data.map((m) => ({ value: m.name, label: m.name }))}
        />
      </div>
    ) : null;

  let body: React.ReactNode;
  if (members.isLoading || (name && data.isLoading)) {
    body = <SkeletonRows rows={4} />;
  } else if (members.error || data.error) {
    body = (
      <ErrorState
        title={tc("errorTitle")}
        description={tc("errorGeneric")}
        onRetry={() => void (members.error ? members.refetch() : data.refetch())}
        retryLabel={tc("retry")}
      />
    );
  } else if (!name) {
    body = <EmptyState icon={<FlaskConical />} title={t("noMembersTitle")} description={t("noMembersDescription")} />;
  } else if (!data.data || data.data.versions.length === 0) {
    body = <EmptyState icon={<FlaskConical />} title={t("emptyTitle")} description={t("emptyDescription")} />;
  } else {
    const versions = data.data.versions;
    body = (
      <TooltipProvider delayDuration={150}>
        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-0.5 text-sm">
            <thead>
              <tr>
                <th className="sticky left-0 bg-surface px-2 py-1.5 text-left text-xs font-medium text-fg-subtle">{t("case")}</th>
                {versions.map((v) => (
                  <th key={v.key} className="min-w-20 px-2 py-1.5 text-center text-xs font-medium text-fg-muted">
                    <Tooltip
                      content={
                        <span className="block max-w-64 text-xs">
                          {v.message ? <span className="block font-medium">{v.message}</span> : null}
                          {v.git_commit ? <span className="block font-mono">{v.git_commit.slice(0, 10)}</span> : null}
                          <span className="block">{t("runsCount", { count: v.eval_runs })}</span>
                          {v.inferred ? <span className="block">{t("inferred")}</span> : null}
                        </span>
                      }
                    >
                      <span className="inline-flex cursor-default flex-col items-center" tabIndex={0}>
                        <span className="text-fg">
                          {versionLabel(v)}
                          {v.inferred ? "*" : ""}
                        </span>
                        <span className="font-normal text-fg-subtle">{formatDate(v.created_at ?? v.last_eval_at, locale)}</span>
                      </span>
                    </Tooltip>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="sticky left-0 bg-surface px-2 py-1.5 text-xs font-semibold text-fg">{t("passRate")}</td>
                {versions.map((v) => (
                  <td key={v.key} className="tabular rounded-sm bg-subtle px-2 py-1.5 text-center text-xs font-semibold">
                    {formatRatio(v.pass_rate, locale, 0)}
                    {v.errored_runs ? <span className="block font-normal text-danger">{t("erroredRuns", { count: v.errored_runs })}</span> : null}
                  </td>
                ))}
              </tr>
              {data.data.cases.map((c) => (
                <tr key={c.name}>
                  <td className="sticky left-0 max-w-[16rem] truncate bg-surface px-2 py-1.5 font-mono text-xs text-fg" title={c.description ?? c.name}>
                    {c.name}
                  </td>
                  {versions.map((v) => {
                    const cell = c.results[v.key];
                    return cell ? (
                      <td
                        key={v.key}
                        className={cn("tabular rounded-sm px-2 py-1.5 text-center text-xs font-medium", tone(cell.rate))}
                        aria-label={t("cellLabel", { passed: cell.passed, total: cell.total })}
                      >
                        {cell.passed}/{cell.total}
                      </td>
                    ) : (
                      <td key={v.key} className="px-2 py-1.5 text-center text-xs text-fg-subtle" aria-label={t("notRun")}>
                        —
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-fg-subtle">{t("legend")}</p>
      </TooltipProvider>
    );
  }

  return (
    <Card className="min-w-0">
      <CardHeader title={t("title")} description={t("description")} actions={picker} />
      <div className="p-4">{body}</div>
    </Card>
  );
}

"use client";

import { TBody, TD, TH, THead, TR, Table, Tooltip } from "@messer/ui";
import { CornerDownRight } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { formatDate, formatDuration, formatRelative, formatUsd, localeTag } from "@/lib/format";
import { formatCredits, modelNames } from "@/lib/studio/format";
import type { RunSummary } from "@/lib/studio/types";

import { RunStatusBadge } from "./run-status-badge";

export function useChannelLabel() {
  const t = useTranslations("traces.channels");
  return (channel: string) => (t.has(channel) ? t(channel) : channel);
}

export function traceHref(projectId: string, runId: string): string {
  return `/app/projects/${projectId}/traces/${runId}`;
}

/** Runs table; rows open the trace detail. `compact` hides secondary columns (project overview). */
export function RunsTable({ runs, compact = false }: { runs: RunSummary[]; compact?: boolean }) {
  const t = useTranslations("traces.table");
  const locale = localeTag(useLocale());
  const router = useRouter();
  const channelLabel = useChannelLabel();
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t("status")}</TH>
          <TH>{t("member")}</TH>
          {compact ? null : <TH className="hidden lg:table-cell">{t("model")}</TH>}
          <TH className="hidden md:table-cell">{t("channel")}</TH>
          {compact ? null : <TH className="hidden xl:table-cell">{t("environment")}</TH>}
          <TH className="text-right">{t("cost")}</TH>
          {compact ? null : <TH className="hidden text-right md:table-cell">{t("credits")}</TH>}
          <TH className="hidden text-right sm:table-cell">{t("duration")}</TH>
          <TH className="text-right">{t("started")}</TH>
        </tr>
      </THead>
      <TBody>
        {runs.map((run) => {
          const href = traceHref(run.project_id, run.id);
          const models = modelNames(run.models);
          return (
            <TR
              key={run.id}
              className="cursor-pointer"
              onClick={(e) => {
                if ((e.target as HTMLElement).closest("a")) return;
                router.push(href);
              }}
            >
              <TD>
                <RunStatusBadge status={run.status} />
              </TD>
              <TD className="max-w-48">
                <Link href={href} className="flex items-center gap-1 truncate font-medium hover:underline">
                  {run.parent_run_id ? (
                    <CornerDownRight className="size-3.5 shrink-0 text-fg-subtle" aria-label={t("continuation")} />
                  ) : null}
                  <span className="truncate font-mono text-xs">{run.workforce_name}</span>
                </Link>
              </TD>
              {compact ? null : (
                <TD className="hidden max-w-48 truncate text-xs text-fg-muted lg:table-cell">{models.join(", ") || "—"}</TD>
              )}
              <TD className="hidden text-fg-muted md:table-cell">{channelLabel(run.channel)}</TD>
              {compact ? null : <TD className="hidden text-fg-muted xl:table-cell">{run.environment}</TD>}
              <TD className="tabular text-right">{formatUsd(run.cost_usd, locale)}</TD>
              {compact ? null : <TD className="tabular hidden text-right md:table-cell">{formatCredits(run.credits, locale)}</TD>}
              <TD className="tabular hidden text-right text-fg-muted sm:table-cell">{formatDuration(run.duration_ms)}</TD>
              <TD className="whitespace-nowrap text-right text-fg-muted">
                <Tooltip content={formatDate(run.started_at, locale, true)}>
                  <time dateTime={run.started_at}>{formatRelative(run.started_at, locale)}</time>
                </Tooltip>
              </TD>
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}

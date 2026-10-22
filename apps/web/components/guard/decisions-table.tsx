"use client";

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from "@messer/ui";
import { ChevronRight, ExternalLink, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { formatDuration, formatRelative, formatUsd, localeTag } from "@/lib/format";

import { useGuardDecisions } from "./hooks";
import type { GuardDecision } from "./types";

const STATUS_TONE = { success: "success", blocked: "danger", invalid_output: "warning", error: "danger" } as const;
const VERDICT_TONE = { allow: "success", deny: "danger", approval: "info", pass: "neutral" } as const;

function shortModel(model: string | null): string {
  if (!model) return "—";
  return model.replace(/^anthropic\/claude-/, "").replace(/-/g, " ");
}

function DecisionDetail({ decision }: { decision: GuardDecision }) {
  const t = useTranslations("guard.decisions");
  const locale = localeTag(useLocale());
  return (
    <div className="grid gap-4 text-xs lg:grid-cols-2">
      <section className="flex flex-col gap-2">
        <h4 className="font-medium text-fg-muted">{t("toolCalls")}</h4>
        {decision.tool_calls.length === 0 ? (
          <p className="text-fg-subtle">—</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {decision.tool_calls.map((call) => (
              <li key={call.id} className="rounded-md border border-border bg-surface px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono font-medium">{call.tool}</span>
                  <Badge tone={VERDICT_TONE[call.verdict]}>{t(`verdicts.${call.verdict}`)}</Badge>
                </div>
                <pre className="mt-1 overflow-x-auto font-mono text-[11px] text-fg-muted">
                  {JSON.stringify(call.input)}
                </pre>
                {call.policies.length ? (
                  <ul className="mt-1 flex flex-wrap gap-1">
                    {call.policies.map((p, i) => (
                      <li key={i}>
                        <Badge tone="outline">
                          <span className="font-mono">{p.policy}</span> ·{" "}
                          {t.has(`reasons.${p.reason}`) ? t(`reasons.${p.reason}`) : p.reason}
                          {p.missing?.length ? ` (${p.missing.join(", ")})` : ""}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {call.explanation ? <p className="mt-1 text-danger">{call.explanation}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="flex flex-col gap-3">
        <div>
          <h4 className="mb-1 font-medium text-fg-muted">{t("votes")}</h4>
          {decision.votes.length === 0 ? (
            <p className="text-fg-subtle">—</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {decision.votes.map((v, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono">{v.policy}</span>
                  <span aria-hidden className="tabular tracking-widest">
                    {v.votes.map((x) => (x === true ? "✓" : x === false ? "✗" : "·")).join("")}
                  </span>
                  <span className={v.matched ? "text-success" : "text-fg-muted"}>
                    {v.skipped ? (t.has(`votesSkipped.${v.skipped}`) ? t(`votesSkipped.${v.skipped}`) : v.skipped) : v.matched ? t("matched") : t("notMatched")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h4 className="mb-1 font-medium text-fg-muted">{t("facts")}</h4>
          {decision.facts.length === 0 ? (
            <p className="text-fg-subtle">{t("noFacts")}</p>
          ) : (
            <ul className="flex flex-wrap gap-1">
              {decision.facts.map((f) => (
                <li key={f}>
                  <Badge tone="neutral" className="font-mono">
                    {f}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
        <p className="tabular text-fg-subtle">
          {t("costs", {
            priced: formatUsd(decision.priced_cost_usd ?? 0, locale),
            baseline: formatUsd(decision.baseline_cost_usd ?? 0, locale),
            overhead: formatUsd(decision.overhead_cost_usd, locale),
          })}
          {decision.latency_ms !== null ? ` · ${formatDuration(decision.latency_ms)}` : ""}
        </p>
        {decision.errors.length ? (
          <div>
            <h4 className="mb-1 font-medium text-danger">{t("errors")}</h4>
            <ul className="font-mono text-[11px] text-danger">
              {decision.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function DecisionRow({ decision, projectId }: { decision: GuardDecision; projectId: string }) {
  const t = useTranslations("guard.decisions");
  const locale = localeTag(useLocale());
  const [open, setOpen] = React.useState(false);
  const status = decision.status as keyof typeof STATUS_TONE;
  const turnText =
    decision.turn === "tool_result" ? t("toolResult") : decision.text || "—";
  return (
    <>
      <TR>
        <TD className="w-8">
          <button
            type="button"
            className="rounded-sm p-0.5 hover:bg-muted"
            aria-expanded={open}
            aria-label={t("toggle")}
            onClick={() => setOpen((o) => !o)}
          >
            <ChevronRight className={open ? "size-4 rotate-90 transition-transform" : "size-4 transition-transform"} />
          </button>
        </TD>
        <TD className="whitespace-nowrap text-fg-muted">{formatRelative(decision.at, locale)}</TD>
        <TD className="max-w-[18rem]">
          <p className="truncate" title={decision.text}>
            {turnText}
          </p>
        </TD>
        <TD>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-xs">
              {decision.policy === "fallthrough" ? t("fallthrough") : decision.policy}
            </span>
            {!decision.on_path ? <Badge tone="outline">{t("offPath")}</Badge> : null}
            {decision.demo ? <Badge tone="outline">{t("demo")}</Badge> : null}
          </div>
        </TD>
        <TD className="hidden whitespace-nowrap text-xs text-fg-muted md:table-cell">
          {decision.route === "answer" ? t("answer") : shortModel(decision.model)}
        </TD>
        <TD>
          <Badge tone={STATUS_TONE[status] ?? "neutral"}>{t.has(`status.${status}`) ? t(`status.${status}`) : status}</Badge>
        </TD>
        <TD className="w-10 text-right">
          <Button asChild variant="ghost" size="icon-sm" aria-label={t("trace")}>
            <Link href={`/app/projects/${projectId}/traces/${decision.run_id}`}>
              <ExternalLink />
            </Link>
          </Button>
        </TD>
      </TR>
      {open ? (
        <tr>
          <td colSpan={7} className="bg-subtle/60 px-3 py-3">
            <DecisionDetail decision={decision} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

export function DecisionsTable({ projectId, member }: { projectId: string; member: string }) {
  const t = useTranslations("guard.decisions");
  const tc = useTranslations("common");
  const decisions = useGuardDecisions(projectId, member);

  if (decisions.isLoading) return <SkeletonRows rows={5} />;
  if (decisions.error) {
    return (
      <ErrorState
        title={tc("errorTitle")}
        description={tc("errorGeneric")}
        onRetry={() => void decisions.refetch()}
        retryLabel={tc("retry")}
      />
    );
  }
  const rows = decisions.data ?? [];
  if (rows.length === 0) {
    return <EmptyState icon={<ShieldCheck />} title={t("empty.title")} description={t("empty.description")} />;
  }
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-fg-muted">{t("description")}</p>
      <div className="overflow-x-auto rounded-md border border-border">
        <Table>
          <THead>
            <TR>
              <TH className="w-8" />
              <TH>{t("columns.at")}</TH>
              <TH>{t("columns.turn")}</TH>
              <TH>{t("columns.policy")}</TH>
              <TH className="hidden md:table-cell">{t("columns.model")}</TH>
              <TH>{t("columns.result")}</TH>
              <TH className="w-10" />
            </TR>
          </THead>
          <TBody>
            {rows.map((d) => (
              <DecisionRow key={d.span_id} decision={d} projectId={projectId} />
            ))}
          </TBody>
        </Table>
      </div>
    </div>
  );
}

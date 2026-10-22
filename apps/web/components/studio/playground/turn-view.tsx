"use client";

import { Alert, Badge, Spinner, StatusDot, cn } from "@messer/ui";
import { Bot, ChevronRight, FileText, Info, ShieldAlert, Square, Wrench } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApprovalStatusBadge } from "@/components/approvals/approval-status-badge";
import { DecisionPanel } from "@/components/approvals/decision-panel";
import { PayloadView } from "@/components/approvals/payload-view";
import { RunStatusBadge } from "@/components/traces/run-status-badge";
import { traceHref } from "@/components/traces/runs-table";
import { formatDuration, formatUsd, localeTag } from "@/lib/format";
import { useMe } from "@/lib/hooks/use-me";
import type { ApprovalPart, AssistantTurn, Part, ToolPart, UserTurn } from "@/lib/studio/chat";
import { formatCredits, toUuid } from "@/lib/studio/format";
import type { DecisionBody } from "@/lib/studio/types";
import { hasRole } from "@/lib/types";

import { JsonView } from "../json-view";
import { Markdown } from "../markdown";

const TOOL_TONE = {
  streaming: "info",
  running: "info",
  done: "success",
  error: "danger",
  awaiting_approval: "warning",
  approved: "success",
  denied: "danger",
  blocked: "danger",
} as const;

function ToolCard({ part }: { part: ToolPart }) {
  const t = useTranslations("studio.playground.tool");
  const [open, setOpen] = React.useState(false);
  const tone = TOOL_TONE[part.state];
  const busy = part.state === "streaming" || part.state === "running";
  return (
    <div className="rounded-md border border-border bg-surface">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <ChevronRight className={cn("size-4 shrink-0 text-fg-subtle transition-transform", open && "rotate-90")} aria-hidden />
        <Wrench className="size-4 shrink-0 text-fg-subtle" aria-hidden />
        <span className="min-w-0 flex-1 truncate">
          <span className="text-fg-muted">{t("call")} </span>
          <span className="font-mono text-xs font-medium">{part.name}</span>
        </span>
        <Badge tone={tone}>
          {busy ? <Spinner className="size-3 border" label={t(`state.${part.state}`)} /> : <StatusDot tone={tone} />}
          {t(`state.${part.state}`)}
        </Badge>
      </button>
      {open ? (
        <div className="flex flex-col gap-2 border-t border-border px-3 py-2.5">
          <div>
            <p className="mb-1 text-xs font-medium text-fg-muted">{t("input")}</p>
            <JsonView value={part.input} defaultDepth={2} emptyLabel={t("noInput")} />
          </div>
          {part.error !== undefined && part.error !== null ? (
            <div>
              <p className="mb-1 text-xs font-medium text-danger">{t("error")}</p>
              <JsonView value={part.error} />
            </div>
          ) : (
            <div>
              <p className="mb-1 text-xs font-medium text-fg-muted">{t("result")}</p>
              {part.output === undefined ? (
                <p className="text-xs text-fg-subtle">{t(part.state === "awaiting_approval" ? "awaitingResult" : part.state === "approved" ? "resumedResult" : "noResult")}</p>
              ) : (
                <JsonView value={part.output} defaultDepth={2} />
              )}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function ApprovalCard({
  part,
  onDecide,
}: {
  part: ApprovalPart;
  onDecide: (part: ApprovalPart, body: DecisionBody) => void;
}) {
  const t = useTranslations("studio.playground.approval");
  const { data: me } = useMe();
  const role = part.assignedRole ?? "admin";
  const canDecide = hasRole(me, role);
  const decided = part.state === "approved" || part.state === "denied" || part.state === "expired";
  return (
    <section
      className="rounded-md border border-warning/40 bg-warning-soft/40"
      aria-label={t("label", { tool: part.toolName })}
    >
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-warning/25 px-3 py-2.5">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{t("title")}</p>
          <p className="text-xs text-fg-muted">{part.title || t("fallback", { tool: part.toolName })}</p>
        </div>
        <span className="flex items-center gap-1.5">
          <Badge tone="outline" className="font-mono">
            {part.toolName}
          </Badge>
          {decided ? <ApprovalStatusBadge status={part.state as "approved" | "denied" | "expired"} /> : null}
        </span>
      </div>
      <div className="flex flex-col gap-3 px-3 py-3">
        <PayloadView payload={part.input} schema={part.inputSchema} />
        {part.state === "requested" ? (
          <p className="flex items-center gap-2 text-xs text-fg-muted">
            <Spinner className="size-3" />
            {t("registering")}
          </p>
        ) : decided ? (
          part.comment ? <p className="text-xs text-fg-muted">{t("comment", { comment: part.comment })}</p> : null
        ) : (
          <DecisionPanel
            idPrefix={`pg-${part.id}`}
            payload={part.input}
            schema={part.inputSchema}
            canDecide={canDecide}
            assignedRole={role}
            busy={part.state === "deciding" ? part.decision : null}
            error={part.error}
            onDecide={(body) => onDecide(part, body)}
          />
        )}
        {part.approvalId ? (
          <Link href={`/app/approvals?id=${part.approvalId}`} className="self-start text-xs text-fg-muted underline-offset-2 hover:underline">
            {t("openInbox")}
          </Link>
        ) : null}
      </div>
    </section>
  );
}

function PartView({ part, onDecide }: { part: Part; onDecide: (part: ApprovalPart, body: DecisionBody) => void }) {
  const t = useTranslations("studio.playground");
  switch (part.type) {
    case "text":
      return part.text ? <Markdown source={part.text} /> : null;
    case "thinking":
      return (
        <details className="rounded-md border border-border px-3 py-2 text-xs text-fg-muted">
          <summary className="cursor-pointer select-none font-medium">{t("thinking")}</summary>
          <p className="mt-1.5 whitespace-pre-wrap">{part.text}</p>
        </details>
      );
    case "tool":
      return <ToolCard part={part} />;
    case "guardrail":
      return (
        <p className={cn("flex items-start gap-2 rounded-md border px-3 py-2 text-xs", part.shadow ? "border-border text-fg-muted" : "border-danger/30 bg-danger-soft/50 text-fg")}>
          <ShieldAlert className={cn("mt-px size-4 shrink-0", part.shadow ? "text-fg-subtle" : "text-danger")} aria-hidden />
          <span>
            {t("guardrail", {
              rail: part.rail,
              action: t.has(`guardrailActions.${part.action}`) ? t(`guardrailActions.${part.action}`) : part.action,
              stage: t.has(`guardrailStages.${part.stage}`) ? t(`guardrailStages.${part.stage}`) : part.stage,
            })}
            {part.shadow ? <Badge tone="outline" className="ml-1.5">{t("shadow")}</Badge> : null}
            {part.reason ? <span className="mt-0.5 block text-fg-subtle">{part.reason}</span> : null}
          </span>
        </p>
      );
    case "approval":
      return <ApprovalCard part={part} onDecide={onDecide} />;
    case "error":
      return (
        <Alert tone="danger" title={t("errorTitle")}>
          {part.message}
        </Alert>
      );
    default:
      return null;
  }
}

function RunFooter({ turn, projectId }: { turn: AssistantTurn; projectId: string }) {
  const t = useTranslations("studio.playground.footer");
  const locale = localeTag(useLocale());
  const f = turn.finished;
  const runId = f?.runId || turn.runId;
  if (!f && !runId) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-muted">
        {f ? <RunStatusBadge status={f.status} /> : null}
        {f && f.durationMs !== null ? (
          <span className="tabular">
            <span className="sr-only">{t("duration")} </span>
            {formatDuration(f.durationMs)}
          </span>
        ) : null}
        {f ? (
          <span className="tabular">
            {t("cost")} {formatUsd(f.costUsd, locale)}
          </span>
        ) : null}
        {f ? (
          <span className="tabular">
            {t("credits", { value: formatCredits(f.credits, locale) })}
          </span>
        ) : null}
        {turn.model ? <span className="font-mono">{turn.model}</span> : null}
        {runId ? (
          <Link href={traceHref(projectId, toUuid(runId))} className="font-medium text-fg underline-offset-2 hover:underline">
            {t("viewTrace")}
          </Link>
        ) : null}
      </div>
      {f?.demo ? (
        <p className="flex items-center gap-1.5 text-[11px] text-fg-subtle">
          <Info className="size-3.5" aria-hidden />
          {t("demo")}
        </p>
      ) : null}
    </div>
  );
}

export function UserTurnView({ turn }: { turn: UserTurn }) {
  const t = useTranslations("studio.playground");
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-md border border-border bg-subtle px-3 py-2 text-sm">
        <span className="sr-only">{t("you")}: </span>
        <p className="whitespace-pre-wrap break-words">{turn.text}</p>
        {turn.attachments.length > 0 ? (
          <ul className="mt-2 flex flex-wrap gap-1" aria-label={t("attachments")}>
            {turn.attachments.map((name, i) => (
              <li key={`${name}-${i}`}>
                <Badge tone="outline" className="gap-1">
                  <FileText className="size-3" aria-hidden />
                  {name}
                </Badge>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

export function AssistantTurnView({
  turn,
  projectId,
  onDecide,
}: {
  turn: AssistantTurn;
  projectId: string;
  onDecide: (part: ApprovalPart, body: DecisionBody) => void;
}) {
  const t = useTranslations("studio.playground");
  const hasText = turn.parts.some((p) => p.type === "text" && p.text);
  return (
    <div className="flex gap-2.5" aria-busy={turn.streaming || undefined}>
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border border-border bg-surface" aria-hidden>
        <Bot className="size-3.5 text-fg-muted" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2.5">
        <span className="sr-only">{t("assistant")}: </span>
        {turn.resumeOf ? <p className="text-xs font-medium text-fg-subtle">{t("resumed")}</p> : null}
        {turn.parts.map((part) => (
          <PartView key={part.id} part={part} onDecide={onDecide} />
        ))}
        {turn.streaming && !hasText ? (
          <p className="flex items-center gap-2 text-xs text-fg-muted">
            <Spinner className="size-3" label={t("thinkingNow")} />
            {t("thinkingNow")}
          </p>
        ) : null}
        {turn.waitingOthers ? <Alert tone="info">{t("waitingOthers")}</Alert> : null}
        {turn.stopped ? (
          <p className="flex items-center gap-1.5 text-xs text-fg-subtle">
            <Square className="size-3" aria-hidden />
            {t("stopped")}
          </p>
        ) : null}
        {!turn.streaming ? <RunFooter turn={turn} projectId={projectId} /> : null}
      </div>
    </div>
  );
}

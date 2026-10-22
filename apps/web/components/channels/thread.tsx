"use client";

import { Badge, Spinner, StatusDot, cn } from "@messer/ui";
import { Activity, AlertTriangle, Clock, Paperclip } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Markdown } from "@/components/studio/markdown";
import { traceHref } from "@/components/traces/runs-table";
import { formatDate, localeTag } from "@/lib/format";

import type { Delivery, ThreadMessage } from "./types";

const DELIVERY_TONE: Record<string, "success" | "info" | "danger" | "warning" | "neutral"> = {
  sent: "success",
  stored: "info",
  failed: "danger",
  received: "warning",
  processing: "warning",
};

function DeliveryBadge({ delivery, demo }: { delivery: Delivery; demo: boolean }) {
  const t = useTranslations("channels.thread.delivery");
  const key = delivery.status === "stored" && !demo ? "simulated" : delivery.status;
  const busy = delivery.status === "received" || delivery.status === "processing";
  return (
    <Badge tone={DELIVERY_TONE[delivery.status] ?? "neutral"}>
      {busy ? <Spinner className="size-3 border" label={t(key)} /> : <StatusDot tone={DELIVERY_TONE[delivery.status] ?? "neutral"} />}
      {t.has(key) ? t(key) : delivery.status}
      {delivery.parts && delivery.parts > 1 ? <span className="tabular">· {t("parts", { count: delivery.parts })}</span> : null}
    </Badge>
  );
}

/**
 * A conversation thread. ``perspective="agent"`` (inbox) puts the agent's messages on the right;
 * ``perspective="user"`` (simulator) puts the user's on the right, like a phone.
 */
export function Thread({
  messages,
  projectId,
  perspective,
  demo,
  agentName,
  contactName,
}: {
  messages: ThreadMessage[];
  projectId: string;
  perspective: "agent" | "user";
  demo: boolean;
  agentName: string;
  contactName: string;
}) {
  const t = useTranslations("channels.thread");
  const locale = localeTag(useLocale());
  return (
    <ol className="flex flex-col gap-3" aria-label={t("label")}>
      {messages.map((m) => {
        const mine = perspective === "agent" ? m.role === "assistant" : m.role === "user";
        const notice = m.notice;
        return (
          <li key={`${m.index}-${m.role}`} className={cn("flex flex-col gap-1", mine ? "items-end" : "items-start")}>
            <span className="px-1 text-xs text-fg-subtle">
              {m.role === "assistant" ? agentName : contactName}
              {m.at ? <span className="tabular"> · {formatDate(m.at, locale, true)}</span> : null}
            </span>
            <div
              className={cn(
                "max-w-[85%] rounded-md border px-3 py-2 text-sm",
                notice === "error" || m.error
                  ? "border-danger/30 bg-danger-soft/40"
                  : notice === "approval_pending"
                    ? "border-warning/40 bg-warning-soft/40"
                    : mine
                      ? "border-border-strong bg-subtle"
                      : "border-border bg-surface",
              )}
            >
              {notice ? (
                <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-fg-muted">
                  {notice === "approval_pending" ? <Clock className="size-3.5" aria-hidden /> : <AlertTriangle className="size-3.5" aria-hidden />}
                  {t(`notice.${notice}`)}
                </p>
              ) : null}
              {m.role === "assistant" ? <Markdown source={m.text} /> : <p className="whitespace-pre-wrap break-words">{m.text}</p>}
              {m.attachments.length ? (
                <p className="mt-1.5 flex items-center gap-1 text-xs text-fg-muted">
                  <Paperclip className="size-3.5" aria-hidden />
                  {m.attachments.join(", ")}
                </p>
              ) : null}
              {m.error ? (
                <p className="mt-1.5 text-xs text-danger">
                  {t("notProcessed")}: {m.error.message ?? m.error.code}
                </p>
              ) : null}
            </div>
            <span className="flex flex-wrap items-center gap-1.5 px-1">
              {m.delivery ? <DeliveryBadge delivery={m.delivery} demo={demo} /> : null}
              {m.delivery?.status === "failed" && m.delivery.error ? (
                <span className="max-w-md text-xs text-danger">{m.delivery.error}</span>
              ) : null}
              {m.run_id ? (
                <Link
                  href={traceHref(projectId, m.run_id)}
                  className="inline-flex items-center gap-1 text-xs text-fg-muted underline-offset-2 hover:text-fg hover:underline"
                >
                  <Activity className="size-3.5" aria-hidden />
                  {t("trace")}
                </Link>
              ) : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

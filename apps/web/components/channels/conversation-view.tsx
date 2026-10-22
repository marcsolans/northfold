"use client";

import { Alert, Badge, Button, EmptyState, ErrorState, SkeletonRows, toast } from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, CheckCircle2, MessageSquareOff, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { traceHref } from "@/components/traces/runs-table";
import { http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";
import { errorMessage, isNotFound } from "@/lib/studio/hooks";

import { channelHref } from "./channels-page";
import { channelKeys, useConversation, useConversationEvents } from "./hooks";
import { ProviderIcon, useProviderLabel } from "./provider-icon";
import { Thread } from "./thread";
import type { ConversationDetail } from "./types";

export function ConversationView({
  conversationId,
  projectId,
  canBuild,
}: {
  conversationId: string;
  projectId: string;
  canBuild: boolean;
}) {
  const t = useTranslations("channels.inbox");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const label = useProviderLabel();
  const qc = useQueryClient();
  const conv = useConversation(conversationId);
  const live = useConversationEvents(conversationId, projectId);

  const setStatus = useMutation({
    mutationFn: (action: "close" | "reopen") => http.post<ConversationDetail>(`/conversations/${conversationId}/${action}`),
    onSuccess: (updated) => {
      qc.setQueryData(channelKeys.conversation(conversationId), updated);
      void qc.invalidateQueries({ queryKey: channelKeys.inbox(projectId) });
      toast.success(updated.status === "closed" ? t("closedToast") : t("reopenedToast"));
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  if (conv.isLoading) {
    return (
      <div className="p-4">
        <SkeletonRows rows={6} />
      </div>
    );
  }
  if (conv.error || !conv.data) {
    return (
      <div className="p-4">
        {isNotFound(conv.error) ? (
          <EmptyState icon={<MessageSquareOff />} title={t("notFoundTitle")} description={t("notFoundDescription")} />
        ) : (
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void conv.refetch()} retryLabel={tc("retry")} />
        )}
      </div>
    );
  }
  const c = conv.data;
  const contact = c.contact_name || c.contact_id;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-start gap-3">
          <ProviderIcon provider={c.provider} />
          <div className="min-w-0">
            <h2 className="truncate text-md font-semibold" title={c.contact_id}>
              {contact}
            </h2>
            <p className="truncate text-xs text-fg-muted">
              {c.channel ? (
                <Link href={channelHref(projectId, c.channel.id)} className="hover:text-fg hover:underline">
                  {c.channel.name}
                </Link>
              ) : (
                label(c.provider)
              )}
              {" · "}
              {t("agent", { name: c.workforce_name })}
              {" · "}
              <span className="tabular">{t("since", { date: formatDate(c.created_at, locale, true) })}</span>
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              <Badge tone={c.status === "open" ? "success" : "neutral"}>{t(`statuses.${c.status}`)}</Badge>
              {c.simulated ? <Badge tone="outline">{t("simulated")}</Badge> : null}
              {c.channel?.demo ? <Badge tone="info">{t("demo")}</Badge> : null}
              {!live ? <Badge tone="outline">{t("offline")}</Badge> : null}
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          {c.last_run_id ? (
            <Button asChild size="sm" variant="ghost">
              <Link href={traceHref(projectId, c.last_run_id)}>
                <Activity />
                {t("lastTrace")}
              </Link>
            </Button>
          ) : null}
          {canBuild ? (
            c.status === "open" ? (
              <Button size="sm" variant="secondary" loading={setStatus.isPending} onClick={() => setStatus.mutate("close")}>
                <CheckCircle2 />
                {t("close")}
              </Button>
            ) : (
              <Button size="sm" variant="secondary" loading={setStatus.isPending} onClick={() => setStatus.mutate("reopen")}>
                <RotateCcw />
                {t("reopen")}
              </Button>
            )
          ) : null}
        </div>
      </div>
      {c.pending_approvals.length ? (
        <Alert
          tone="warning"
          className="mx-4 mt-3"
          title={t("pendingTitle", { count: c.pending_approvals.length })}
          action={
            <Button asChild size="sm" variant="dark">
              <Link href={`/app/approvals?id=${c.pending_approvals[0]?.id ?? ""}`}>{t("pendingOpen")}</Link>
            </Button>
          }
        >
          {c.pending_approvals.map((a) => a.title).join(" · ")}
        </Alert>
      ) : null}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {c.messages.length === 0 ? (
          <EmptyState icon={<MessageSquareOff />} title={t("noMessagesTitle")} description={t("noMessagesDescription")} />
        ) : (
          <Thread
            messages={c.messages}
            projectId={projectId}
            perspective="agent"
            demo={Boolean(c.channel?.demo)}
            agentName={c.workforce_name}
            contactName={contact}
          />
        )}
      </div>
    </div>
  );
}

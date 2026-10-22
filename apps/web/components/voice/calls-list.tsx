"use client";

import { Dialog, DialogContent, EmptyState, ErrorState, SkeletonRows, TBody, TD, TH, THead, TR, Table } from "@messer/ui";
import { PhoneCall } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { formatDuration, formatRelative, formatUsd, localeTag } from "@/lib/format";
import { errorMessage } from "@/lib/studio/hooks";

import { useVoiceCalls } from "./api";
import { CallStatusBadge, VoiceCallDetail } from "./call-detail";

/** Recent calls of a project (optionally one agent, number, conversation or transport); a row opens the call. */
export function VoiceCallsList({
  projectId,
  workforce,
  conversationId,
  phoneNumberId,
  transport,
  channel,
  limit = 25,
  emptyDescription,
}: {
  projectId: string;
  workforce?: string;
  conversationId?: string;
  phoneNumberId?: string;
  transport?: string;
  channel?: "voice" | "phone";
  limit?: number;
  emptyDescription?: string;
}) {
  const t = useTranslations("voice.calls");
  const tt = useTranslations("voice.transport");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const [open, setOpen] = React.useState<string | null>(null);
  const query = useVoiceCalls({
    project_id: projectId,
    workforce,
    conversation_id: conversationId,
    phone_number_id: phoneNumberId,
    transport,
    channel,
    limit: String(limit),
  });

  if (query.isLoading) return <SkeletonRows rows={4} />;
  if (query.isError) {
    return (
      <ErrorState
        title={tc("errorTitle")}
        description={errorMessage(query.error, tc("errorGeneric"))}
        onRetry={() => void query.refetch()}
        retryLabel={tc("retry")}
      />
    );
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) {
    return <EmptyState icon={<PhoneCall />} title={t("emptyTitle")} description={emptyDescription ?? t("emptyDescription")} />;
  }
  return (
    <>
      <Table>
        <THead>
          <tr>
            <TH>{t("when")}</TH>
            <TH>{t("agent")}</TH>
            <TH>{t("channel")}</TH>
            <TH>{tc("status")}</TH>
            <TH className="text-right">{t("turns")}</TH>
            <TH className="text-right">{t("duration")}</TH>
            <TH className="text-right">{t("cost")}</TH>
          </tr>
        </THead>
        <TBody>
          {items.map((call) => (
            <TR
              key={call.id}
              className="cursor-pointer"
              tabIndex={0}
              onClick={() => setOpen(call.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setOpen(call.id);
                }
              }}
            >
              <TD className="whitespace-nowrap text-fg-muted">{formatRelative(call.created_at, locale)}</TD>
              <TD>{call.workforce_name}</TD>
              <TD className="whitespace-nowrap">
                {tt(call.transport)}
                {call.channel === "phone" ? (
                  <span className="text-fg-muted"> · {call.direction === "inbound" ? call.from_number : call.to_number}</span>
                ) : null}
                {call.has_recording ? <span className="ml-1 text-xs text-fg-subtle">● {t("recorded")}</span> : null}
              </TD>
              <TD>
                <CallStatusBadge call={call} />
              </TD>
              <TD className="tabular text-right">{call.turns}</TD>
              <TD className="tabular text-right">{formatDuration(call.duration_ms)}</TD>
              <TD className="tabular text-right">{formatUsd(call.total_cost_usd, locale)}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
      <Dialog open={open !== null} onOpenChange={(o) => (o ? null : setOpen(null))}>
        {open ? (
          <DialogContent title={t("detailTitle")} wide>
            <VoiceCallDetail callId={open} />
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}

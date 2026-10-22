"use client";

import { Badge, Button, Card, EmptyState, ErrorState, SkeletonRows, StatusDot, TBody, TD, TH, THead, TR, Table } from "@messer/ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowUpRight, Inbox } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { traceHref } from "@/components/traces/runs-table";
import { http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";

import { channelKeys } from "./hooks";
import type { Channel, ChannelMessagePage } from "./types";

const TONE: Record<string, "success" | "info" | "danger" | "warning" | "neutral"> = {
  processed: "success",
  sent: "success",
  stored: "info",
  received: "warning",
  processing: "warning",
  ignored: "neutral",
  failed: "danger",
};

/** Delivery log of a channel: every message received and sent, with status and errors. */
export function ActivityLog({ channel, projectId }: { channel: Channel; projectId: string }) {
  const t = useTranslations("channels.activity");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const log = useInfiniteQuery({
    queryKey: channelKeys.messages(channel.id),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      http.get<ChannelMessagePage>(`/channels/${channel.id}/messages`, { cursor: pageParam, limit: 50 }, signal),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: 15_000,
  });
  const items = log.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Card>
      {log.isLoading ? (
        <div className="p-4">
          <SkeletonRows rows={6} />
        </div>
      ) : log.error ? (
        <div className="p-4">
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void log.refetch()} retryLabel={tc("retry")} />
        </div>
      ) : items.length === 0 ? (
        <div className="p-4">
          <EmptyState icon={<Inbox />} title={t("emptyTitle")} description={t("emptyDescription")} />
        </div>
      ) : (
        <>
          <Table>
            <THead>
              <tr>
                <TH>{t("when")}</TH>
                <TH>{t("direction")}</TH>
                <TH className="hidden md:table-cell">{t("contact")}</TH>
                <TH>{t("text")}</TH>
                <TH>{tc("status")}</TH>
                <TH className="text-right">{t("links")}</TH>
              </tr>
            </THead>
            <TBody>
              {items.map((m) => (
                <TR key={m.id}>
                  <TD className="tabular whitespace-nowrap text-xs text-fg-muted">{formatDate(m.created_at, locale, true)}</TD>
                  <TD>
                    <span className="inline-flex items-center gap-1 text-xs">
                      {m.direction === "inbound" ? <ArrowDownLeft className="size-3.5" aria-hidden /> : <ArrowUpRight className="size-3.5" aria-hidden />}
                      {t(`directions.${m.direction}`)}
                      {m.simulated ? <Badge tone="outline">{t("simulated")}</Badge> : null}
                    </span>
                  </TD>
                  <TD className="hidden max-w-[12rem] truncate text-xs md:table-cell" title={m.sender_id ?? undefined}>
                    {m.direction === "inbound" ? m.sender_name || m.sender_id || "—" : "—"}
                  </TD>
                  <TD className="max-w-[24rem]">
                    <p className="truncate text-sm" title={m.text}>
                      {m.text}
                    </p>
                    {m.error ? <p className="truncate text-xs text-danger" title={m.error}>{m.error}</p> : null}
                  </TD>
                  <TD>
                    <Badge tone={TONE[m.status] ?? "neutral"}>
                      <StatusDot tone={TONE[m.status] ?? "neutral"} />
                      {t.has(`statuses.${m.status}`) ? t(`statuses.${m.status}`) : m.status}
                    </Badge>
                  </TD>
                  <TD className="whitespace-nowrap text-right text-xs">
                    {m.conversation_id ? (
                      <Link href={`/app/projects/${projectId}/conversations/${m.conversation_id}`} className="text-fg-muted hover:text-fg hover:underline">
                        {t("conversation")}
                      </Link>
                    ) : null}
                    {m.run_id ? (
                      <Link href={traceHref(projectId, m.run_id)} className="ml-3 text-fg-muted hover:text-fg hover:underline">
                        {t("trace")}
                      </Link>
                    ) : null}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-xs text-fg-muted">
            <span className="tabular">{t("shown", { count: items.length })}</span>
            {log.hasNextPage ? (
              <Button size="sm" variant="secondary" loading={log.isFetchingNextPage} onClick={() => void log.fetchNextPage()}>
                {t("loadMore")}
              </Button>
            ) : null}
          </div>
        </>
      )}
    </Card>
  );
}

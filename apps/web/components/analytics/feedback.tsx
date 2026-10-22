"use client";

import { Card, CardHeader, EmptyState, ErrorState, SkeletonRows, cn } from "@messer/ui";
import { MessageSquareText, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { formatNumber, formatRelative, localeTag } from "@/lib/format";

import { CsvButton } from "./breakdown";
import { VIZ } from "./charts";
import { formatRatio, traceHref } from "./format";
import { type AnalyticsQuery, csvHref, useFeedback } from "./queries";

export function FeedbackCard({ query, enabled }: { query: AnalyticsQuery; enabled: boolean }) {
  const t = useTranslations("analytics.feedback");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const data = useFeedback(query, enabled);
  const fb = data.data;
  const upPct = fb && fb.total ? Math.round((fb.up / fb.total) * 100) : 0;

  return (
    <Card className="flex min-w-0 flex-col">
      <CardHeader title={t("title")} description={t("description")} actions={<CsvButton href={csvHref("feedback", query)} />} />
      <div className={cn("flex flex-1 flex-col gap-4 p-4 transition-opacity", data.isFetching && fb && "opacity-60")}>
        {data.isLoading ? (
          <SkeletonRows rows={4} />
        ) : data.error ? (
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void data.refetch()} retryLabel={tc("retry")} />
        ) : !fb || fb.total === 0 ? (
          <EmptyState icon={<MessageSquareText />} title={t("emptyTitle")} description={t("emptyDescription")} />
        ) : (
          <>
            <div className={VIZ}>
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-xl font-semibold text-fg">{formatRatio(fb.up_ratio, locale, 0)}</p>
                <p className="text-xs text-fg-muted">{t("total", { count: fb.total })}</p>
              </div>
              <div
                className="mt-2 flex h-2 w-full gap-0.5 overflow-hidden rounded-full"
                role="img"
                aria-label={t("meterLabel", { up: fb.up, down: fb.down })}
              >
                {fb.up ? <span className="h-full rounded-l-full bg-[var(--series-1)]" style={{ width: `${upPct}%` }} /> : null}
                {fb.down ? <span className="h-full flex-1 rounded-r-full bg-[var(--series-2)]" /> : null}
              </div>
              <div className="mt-2 flex gap-4 text-xs text-fg-muted">
                <span className="flex items-center gap-1.5">
                  <span aria-hidden className="inline-block size-2 rounded-sm bg-[var(--series-1)]" />
                  <ThumbsUp className="size-3.5" aria-hidden />
                  {t("up", { count: formatNumber(fb.up, locale) })}
                </span>
                <span className="flex items-center gap-1.5">
                  <span aria-hidden className="inline-block size-2 rounded-sm bg-[var(--series-2)]" />
                  <ThumbsDown className="size-3.5" aria-hidden />
                  {t("down", { count: formatNumber(fb.down, locale) })}
                </span>
              </div>
            </div>
            <div>
              <p className="mb-2 text-xs font-medium text-fg-subtle">{t("recent")}</p>
              {fb.comments.length === 0 ? (
                <p className="text-sm text-fg-muted">{t("noComments")}</p>
              ) : (
                <ul className="flex flex-col divide-y divide-border">
                  {fb.comments.map((c) => (
                    <li key={c.id} className="flex gap-2.5 py-2 first:pt-0">
                      {c.value === "up" ? (
                        <ThumbsUp className="mt-0.5 size-4 shrink-0 text-success" aria-label={t("positive")} />
                      ) : (
                        <ThumbsDown className="mt-0.5 size-4 shrink-0 text-danger" aria-label={t("negative")} />
                      )}
                      <div className="min-w-0">
                        <p className="whitespace-pre-line break-words text-sm text-fg">{c.comment}</p>
                        <p className="mt-0.5 truncate text-xs text-fg-subtle">
                          {[c.project_name, c.workforce_name, c.user].filter(Boolean).join(" · ")} · {formatRelative(c.created_at, locale)}
                          {c.project_id ? (
                            <>
                              {" · "}
                              <Link className="text-fg-muted hover:text-fg hover:underline" href={traceHref(c.project_id, c.run_id)}>
                                {t("viewTrace")}
                              </Link>
                            </>
                          ) : null}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

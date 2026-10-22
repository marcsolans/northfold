"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  CopyButton,
  EmptyState,
  ErrorState,
  Field,
  SkeletonRows,
  Textarea,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CornerDownRight, CornerLeftUp, FileSearch, RotateCw, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApprovalStatusBadge } from "@/components/approvals/approval-status-badge";
import { JsonView } from "@/components/studio/json-view";
import { http } from "@/lib/api";
import { formatDate, formatDuration, formatNumber, formatUsd, localeTag } from "@/lib/format";
import { useMe, useRole } from "@/lib/hooks/use-me";
import { formatCredits, modelNames, shortHash, toNumber } from "@/lib/studio/format";
import { errorMessage, isNotFound, studioKeys, useCredits, useRun } from "@/lib/studio/hooks";
import type { RunDetail, RunSummary, Span } from "@/lib/studio/types";

import { RunStatusBadge } from "./run-status-badge";
import { traceHref, useChannelLabel } from "./runs-table";
import { SpanTree, spanDuration, spanRange, useSpanKindLabel } from "./span-tree";

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 truncate text-sm">{children}</dd>
    </div>
  );
}

function SpanDetail({ span, runStart }: { span: Span; runStart: number }) {
  const t = useTranslations("traces.detail");
  const locale = localeTag(useLocale());
  const kindLabel = useSpanKindLabel();
  const duration = spanDuration(span);
  const hasError = span.error !== null && span.error !== undefined;
  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="outline" className="uppercase">
            {kindLabel(span.kind)}
          </Badge>
          <h3 className="font-mono text-sm font-semibold">{span.name}</h3>
          <Badge tone={span.status === "success" ? "success" : span.status === "error" || hasError ? "danger" : "neutral"}>{span.status}</Badge>
        </div>
        <p className="mt-1 break-all font-mono text-[11px] text-fg-subtle">{span.path}</p>
      </div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Meta label={t("start")}>+{formatDuration(span.t0 - runStart)}</Meta>
        <Meta label={t("duration")}>{formatDuration(duration)}</Meta>
        <Meta label={t("cost")}>{formatUsd(span.cost_usd, locale)}</Meta>
        {span.model ? <Meta label={t("model")}><span className="font-mono text-xs">{span.model}</span></Meta> : null}
        {span.kind === "llm" || span.input_tokens + span.output_tokens > 0 ? (
          <>
            <Meta label={t("inputTokens")}>{formatNumber(span.input_tokens, locale)}</Meta>
            <Meta label={t("outputTokens")}>{formatNumber(span.output_tokens, locale)}</Meta>
            {span.cache_read_tokens > 0 ? <Meta label={t("cacheTokens")}>{formatNumber(span.cache_read_tokens, locale)}</Meta> : null}
          </>
        ) : null}
      </dl>
      {hasError ? (
        <section>
          <h4 className="mb-1 text-xs font-semibold text-danger">{t("error")}</h4>
          <JsonView value={span.error} />
        </section>
      ) : null}
      <section>
        <h4 className="mb-1 text-xs font-semibold text-fg-muted">{t("input")}</h4>
        <JsonView value={span.input} />
      </section>
      <section>
        <h4 className="mb-1 text-xs font-semibold text-fg-muted">{t("output")}</h4>
        <JsonView value={span.output} />
      </section>
      {Object.keys(span.meta ?? {}).length > 0 ? (
        <details>
          <summary className="cursor-pointer text-xs font-semibold text-fg-muted">{t("metadata")}</summary>
          <JsonView value={span.meta} className="mt-1" defaultDepth={1} />
        </details>
      ) : null}
    </div>
  );
}

function FeedbackBox({ run }: { run: RunDetail }) {
  const t = useTranslations("traces.feedback");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const { data: me } = useMe();
  const mine = run.feedback.find((f) => f.user_id === me?.id) ?? null;
  const [value, setValue] = React.useState<"up" | "down" | null>(mine?.value ?? null);
  const [comment, setComment] = React.useState(mine?.comment ?? "");
  const [editing, setEditing] = React.useState(false);

  const send = useMutation({
    mutationFn: (body: { value: "up" | "down"; comment: string | null }) => http.post(`/runs/${run.id}/feedback`, body),
    onSuccess: () => {
      setEditing(false);
      toast.success(t("thanks"));
      void qc.invalidateQueries({ queryKey: studioKeys.run(run.id) });
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const choose = (v: "up" | "down") => {
    setValue(v);
    setEditing(true);
  };
  const ups = run.feedback.filter((f) => f.value === "up").length;
  const downs = run.feedback.filter((f) => f.value === "down").length;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        <span className="mr-1 text-xs text-fg-muted">{t("question")}</span>
        <Button size="icon-sm" variant={value === "up" ? "secondary" : "ghost"} aria-pressed={value === "up"} aria-label={t("up")} onClick={() => choose("up")}>
          <ThumbsUp />
        </Button>
        <Button size="icon-sm" variant={value === "down" ? "secondary" : "ghost"} aria-pressed={value === "down"} aria-label={t("down")} onClick={() => choose("down")}>
          <ThumbsDown />
        </Button>
        {ups + downs > 0 ? <span className="tabular ml-1 text-xs text-fg-subtle">{t("summary", { up: ups, down: downs })}</span> : null}
      </div>
      {editing && value ? (
        <div className="flex flex-col gap-2">
          <Field label={t("comment")} htmlFor="feedback-comment" hint={tc("optional")}>
            <Textarea id="feedback-comment" rows={2} maxLength={4000} value={comment} onChange={(e) => setComment(e.target.value)} />
          </Field>
          <div className="flex gap-2">
            <Button size="sm" variant="primary" loading={send.isPending} onClick={() => send.mutate({ value, comment: comment.trim() || null })}>
              {t("send")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(false);
                setValue(mine?.value ?? null);
                setComment(mine?.comment ?? "");
              }}
            >
              {tc("cancel")}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function errorText(error: unknown): string {
  if (!error) return "";
  if (typeof error === "string") return error;
  const e = error as { message?: unknown };
  return typeof e.message === "string" ? e.message : JSON.stringify(error);
}

export function TraceDetail({ projectId, runId }: { projectId: string; runId: string }) {
  const t = useTranslations("traces.detail");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const router = useRouter();
  const canRerun = useRole("builder");
  const channelLabel = useChannelLabel();
  const run = useRun(runId);
  const credits = useCredits();
  const [selected, setSelected] = React.useState<string | null>(null);

  const rerun = useMutation({
    mutationFn: () => http.post<RunSummary>(`/runs/${runId}/rerun`),
    onSuccess: (next) => {
      toast.success(t("rerunStarted"));
      router.push(traceHref(next.project_id, next.id));
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const data = run.data;
  const spans = data?.spans ?? [];
  const root = spans.find((s) => !s.parent_span_id) ?? spans[0] ?? null;
  const current = spans.find((s) => s.id === selected) ?? root;
  const { start } = spanRange(spans);

  if (run.isLoading) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-6 md:px-6">
        <SkeletonRows rows={10} />
      </div>
    );
  }
  if (run.error || !data) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10">
        {isNotFound(run.error) ? (
          <EmptyState
            icon={<FileSearch />}
            title={t("notFound.title")}
            description={t("notFound.description")}
            action={
              <Button asChild variant="secondary">
                <Link href={`/app/projects/${projectId}/traces`}>{t("back")}</Link>
              </Button>
            }
          />
        ) : (
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void run.refetch()} retryLabel={tc("retry")} />
        )}
      </div>
    );
  }

  const models = modelNames(data.models);
  const totalTokens = spans.reduce((acc, s) => acc + s.input_tokens + s.output_tokens, 0);
  const failedMessage = data.status !== "success" && data.status !== "paused" && data.status !== "running" ? errorText(data.error) : "";

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-6 md:px-6">
      <div className="flex flex-wrap items-start gap-3">
        <Button asChild variant="ghost" size="icon-sm" aria-label={t("back")}>
          <Link href={`/app/projects/${projectId}/traces`}>
            <ArrowLeft />
          </Link>
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="flex flex-wrap items-center gap-2 text-lg font-semibold">
            <span className="font-mono">{data.workforce_name}</span>
            <RunStatusBadge status={data.status} />
          </h1>
          <p className="mt-0.5 flex items-center gap-1 font-mono text-xs text-fg-subtle">
            {data.id}
            <CopyButton value={data.id} label={tc("copy")} />
          </p>
        </div>
        {canRerun ? (
          <Button variant="secondary" loading={rerun.isPending} onClick={() => rerun.mutate()}>
            <RotateCw />
            {t("rerun")}
          </Button>
        ) : null}
      </div>

      <Card>
        <dl className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3 lg:grid-cols-6">
          <Meta label={t("duration")}>
            <span className="tabular">{formatDuration(data.duration_ms)}</span>
          </Meta>
          <Meta label={t("cost")}>
            <span className="tabular">{formatUsd(data.cost_usd, locale)}</span>
          </Meta>
          <Meta label={t("credits")}>
            <span className="tabular">{formatCredits(data.credits, locale)}</span>
            {credits.data ? (
              <span className="block text-[11px] text-fg-subtle">{t("balance", { value: formatCredits(credits.data.balance, locale) })}</span>
            ) : null}
          </Meta>
          <Meta label={t("models")}>
            <span className="font-mono text-xs" title={models.join(", ")}>
              {models.join(", ") || "—"}
            </span>
          </Meta>
          <Meta label={t("tokens")}>
            <span className="tabular">{formatNumber(totalTokens, locale)}</span>
          </Meta>
          <Meta label={t("commit")}>
            <span className="font-mono text-xs" title={data.git_commit ?? undefined}>
              {shortHash(data.git_commit)}
            </span>
          </Meta>
          <Meta label={t("environment")}>{t.has(`env.${data.environment}`) ? t(`env.${data.environment}`) : data.environment}</Meta>
          <Meta label={t("channel")}>{channelLabel(data.channel)}</Meta>
          <Meta label={t("user")}>
            <span className="font-mono text-xs">{data.external_user_id ?? (data.user_id ? data.user_id.slice(0, 8) : "—")}</span>
          </Meta>
          <Meta label={t("started")}>{formatDate(data.started_at, locale, true)}</Meta>
          <Meta label={t("ended")}>{data.ended_at ? formatDate(data.ended_at, locale, true) : "—"}</Meta>
          <Meta label={t("project")}>{data.project_name ?? "—"}</Meta>
        </dl>
        {data.parent_run_id || data.children.length > 0 || data.rerun_of ? (
          <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-border px-4 py-2.5 text-xs">
            {data.parent_run_id ? (
              <Link href={traceHref(projectId, data.parent_run_id)} className="flex items-center gap-1 text-fg-muted hover:text-fg hover:underline">
                <CornerLeftUp className="size-3.5" aria-hidden />
                {t("parent", { id: data.parent_run_id.slice(0, 8) })}
              </Link>
            ) : null}
            {data.rerun_of ? (
              <Link href={traceHref(projectId, data.rerun_of)} className="flex items-center gap-1 text-fg-muted hover:text-fg hover:underline">
                <RotateCw className="size-3.5" aria-hidden />
                {t("rerunOf", { id: data.rerun_of.slice(0, 8) })}
              </Link>
            ) : null}
            {data.children.map((child) => (
              <Link key={child} href={traceHref(projectId, child)} className="flex items-center gap-1 text-fg-muted hover:text-fg hover:underline">
                <CornerDownRight className="size-3.5" aria-hidden />
                {t("child", { id: child.slice(0, 8) })}
              </Link>
            ))}
          </div>
        ) : null}
      </Card>

      {failedMessage ? <Alert tone="danger" title={t("failed")}>{failedMessage}</Alert> : null}
      {toNumber(data.cost_usd) === 0 && models.some((m) => m.startsWith("messer/demo")) ? (
        <Alert tone="info">{t("demoNotice")}</Alert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card className="min-w-0 overflow-hidden">
          <CardHeader title={t("spans")} description={t("spansCount", { count: spans.length })} />
          {spans.length === 0 ? (
            <div className="p-4">
              <EmptyState title={t("noSpans")} description={data.status === "running" ? t("runningHint") : t("noSpansHint")} />
            </div>
          ) : (
            <SpanTree spans={spans} selectedId={current?.id ?? null} onSelect={setSelected} />
          )}
        </Card>
        <Card className="min-w-0 lg:sticky lg:top-16 lg:max-h-[calc(100dvh-5rem)] lg:overflow-y-auto">
          {current ? <SpanDetail span={current} runStart={start} /> : <p className="p-4 text-sm text-fg-subtle">{t("selectSpan")}</p>}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("approvals")} />
          {data.approvals.length === 0 ? (
            <p className="px-4 py-4 text-sm text-fg-subtle">{t("noApprovals")}</p>
          ) : (
            <ul className="divide-y divide-border">
              {data.approvals.map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-2 px-4 py-2.5">
                  <ApprovalStatusBadge status={a.status} />
                  <span className="font-mono text-xs">{a.tool_name}</span>
                  <span className="min-w-0 flex-1 truncate text-sm text-fg-muted">{a.title}</span>
                  {a.resume_run_id ? (
                    <Link href={traceHref(projectId, a.resume_run_id)} className="text-xs text-fg-muted hover:underline">
                      {t("resumedRun")}
                    </Link>
                  ) : null}
                  <Link href={`/app/approvals?id=${a.id}`} className="text-xs font-medium hover:underline">
                    {t("openApproval")}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <CardHeader title={t("feedbackTitle")} />
          <div className="p-4">
            <FeedbackBox run={data} />
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title={t("io")} />
        <div className="grid gap-4 p-4 lg:grid-cols-2">
          <section>
            <h3 className="mb-1 text-xs font-semibold text-fg-muted">{t("runInput")}</h3>
            <JsonView value={data.input} />
          </section>
          <section>
            <h3 className="mb-1 text-xs font-semibold text-fg-muted">{t("runOutput")}</h3>
            <JsonView value={data.output} />
          </section>
        </div>
      </Card>
    </div>
  );
}

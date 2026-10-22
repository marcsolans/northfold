"use client";

import {
  Alert,
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Select,
  SkeletonRows,
  StatusDot,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, FlaskConical, Play, XCircle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { previewJson } from "@/lib/studio/format";
import { errorMessage, studioKeys, useEvalRuns } from "@/lib/studio/hooks";
import type { EvalCaseResult, EvalRun } from "@/lib/studio/types";

import { JsonView } from "../json-view";

const STATUS_TONE = { passed: "success", failed: "danger", error: "danger", running: "info" } as const;

function errorText(error: unknown): string {
  if (!error) return "";
  if (typeof error === "string") return error;
  const e = error as { message?: unknown; type?: unknown };
  if (typeof e.message === "string") return typeof e.type === "string" ? `${e.type}: ${e.message}` : e.message;
  return previewJson(error, 400);
}

function CaseRow({ result }: { result: EvalCaseResult }) {
  const t = useTranslations("studio.builder.evals");
  const [open, setOpen] = React.useState(!result.passed);
  const validators = result.validators ?? [];
  return (
    <>
      <TR>
        <TD className="w-8">
          <button
            type="button"
            className="rounded-sm p-0.5 hover:bg-muted"
            aria-expanded={open}
            aria-label={t("toggleCase", { name: result.name ?? "" })}
            onClick={() => setOpen((o) => !o)}
          >
            <ChevronRight className={open ? "size-4 rotate-90 transition-transform" : "size-4 transition-transform"} />
          </button>
        </TD>
        <TD>
          <p className="font-mono text-xs font-medium">{result.name}</p>
          {result.description ? <p className="text-xs text-fg-muted">{result.description}</p> : null}
        </TD>
        <TD>
          {result.passed ? (
            <Badge tone="success">
              <CheckCircle2 className="size-3" aria-hidden />
              {t("pass")}
            </Badge>
          ) : (
            <Badge tone="danger">
              <XCircle className="size-3" aria-hidden />
              {t("fail")}
            </Badge>
          )}
        </TD>
        <TD className="tabular text-right text-fg-muted">
          {t("validatorsCount", { passed: validators.filter((v) => v.passed).length, total: validators.length })}
        </TD>
        <TD className="tabular hidden text-right text-fg-muted sm:table-cell">
          {typeof result.duration === "number" ? `${result.duration.toFixed(2)} s` : "—"}
        </TD>
      </TR>
      {open ? (
        <tr>
          <td colSpan={5} className="bg-subtle/60 px-3 py-3">
            {result.error ? (
              <Alert tone="danger" className="mb-3">
                {errorText(result.error)}
              </Alert>
            ) : null}
            {validators.length === 0 ? (
              <p className="text-xs text-fg-subtle">{t("noValidators")}</p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {validators.map((v, i) => (
                  <li key={i} className="rounded-md border border-border bg-surface px-3 py-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      {v.passed ? (
                        <CheckCircle2 className="size-4 text-success" aria-label={t("pass")} />
                      ) : (
                        <XCircle className="size-4 text-danger" aria-label={t("fail")} />
                      )}
                      <span className="font-mono font-medium">{v.name}</span>
                      <span className="text-fg-subtle">{v.target}</span>
                      {!v.evaluated ? <Badge tone="outline">{t("notEvaluated")}</Badge> : null}
                    </div>
                    <dl className="mt-1.5 grid gap-1 sm:grid-cols-[7rem_1fr]">
                      <dt className="text-fg-subtle">{t("expected")}</dt>
                      <dd className="break-words font-mono">{previewJson(v.value, 300) || "—"}</dd>
                      <dt className="text-fg-subtle">{t("actual")}</dt>
                      <dd className="break-words font-mono">{previewJson(v.actual_value, 300) || "—"}</dd>
                      {v.error ? (
                        <>
                          <dt className="text-danger">{t("error")}</dt>
                          <dd className="break-words text-danger">{v.error}</dd>
                        </>
                      ) : null}
                    </dl>
                  </li>
                ))}
              </ul>
            )}
            {result.output !== undefined && result.output !== null ? (
              <div className="mt-3">
                <p className="mb-1 text-xs font-medium text-fg-muted">{t("output")}</p>
                <JsonView value={result.output} defaultDepth={1} />
              </div>
            ) : null}
          </td>
        </tr>
      ) : null}
    </>
  );
}

export function EvalsTab({ projectId, member, canBuild }: { projectId: string; member: string; canBuild: boolean }) {
  const t = useTranslations("studio.builder.evals");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const runs = useEvalRuns(projectId, member);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const run = useMutation({
    mutationFn: () => http.post<EvalRun>(`/projects/${projectId}/workforce/${encodeURIComponent(member)}/evals`, {}),
    onSuccess: (result) => {
      setSelectedId(result.id);
      qc.setQueryData(studioKeys.evals(projectId, member), (prev: EvalRun[] | undefined) => [
        result,
        ...(prev ?? []).filter((r) => r.id !== result.id),
      ]);
      if (result.status === "passed") toast.success(t("allPassed", { count: result.passed }));
      else if (result.status === "failed") toast.error(t("someFailed", { failed: result.failed, total: result.passed + result.failed }));
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const list = runs.data ?? [];
  const selected = list.find((r) => r.id === selectedId) ?? list[0] ?? null;
  const caseResults = (selected?.results ?? []).filter((r) => r.name !== undefined || r.validators !== undefined);
  const runError = (selected?.results ?? []).find((r) => r.name === undefined && r.error)?.error;

  return (
    <div className="px-4 py-4 md:px-5">
      <div className="flex flex-wrap items-center gap-3">
        <p className="mr-auto max-w-md text-xs text-fg-muted">{t("description", { path: `workforce/${member}/evals/` })}</p>
        {list.length > 1 ? (
          <div className="w-56">
            <Select
              aria-label={t("history")}
              value={selected?.id}
              onValueChange={setSelectedId}
              options={list.map((r) => ({
                value: r.id,
                label: `${formatDate(r.created_at, locale, true)} · ${r.passed}/${r.passed + r.failed}`,
              }))}
            />
          </div>
        ) : null}
        {canBuild ? (
          <Button variant="primary" loading={run.isPending} onClick={() => run.mutate()}>
            <Play />
            {run.isPending ? t("running") : t("run")}
          </Button>
        ) : null}
      </div>

      <div className="mt-4" aria-live="polite">
        {runs.isLoading ? (
          <SkeletonRows rows={3} />
        ) : runs.error ? (
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void runs.refetch()} retryLabel={tc("retry")} />
        ) : !selected ? (
          <EmptyState icon={<FlaskConical />} title={t("empty.title")} description={t("empty.description")} />
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-3 rounded-md border border-border px-3 py-2.5 text-sm">
              <Badge tone={STATUS_TONE[selected.status as keyof typeof STATUS_TONE] ?? "neutral"}>
                <StatusDot tone={STATUS_TONE[selected.status as keyof typeof STATUS_TONE] ?? "neutral"} />
                {t.has(`status.${selected.status}`) ? t(`status.${selected.status}`) : selected.status}
              </Badge>
              <span className="tabular text-success">{t("passedCount", { count: selected.passed })}</span>
              <span className="tabular text-danger">{t("failedCount", { count: selected.failed })}</span>
              <span className="ml-auto text-xs text-fg-subtle">
                {t(`trigger.${selected.trigger === "deploy" || selected.trigger === "composer" ? selected.trigger : "manual"}`)} ·{" "}
                {formatRelative(selected.created_at, locale)}
              </span>
            </div>
            {runError ? <Alert tone="danger" title={t("runError")}>{errorText(runError)}</Alert> : null}
            {caseResults.length === 0 && !runError ? (
              <EmptyState icon={<FlaskConical />} title={t("noCases.title")} description={t("noCases.description", { path: `workforce/${member}/evals/` })} />
            ) : caseResults.length > 0 ? (
              <div className="rounded-md border border-border">
                <Table>
                  <THead>
                    <tr>
                      <TH className="w-8" />
                      <TH>{t("case")}</TH>
                      <TH>{t("result")}</TH>
                      <TH className="text-right">{t("validators")}</TH>
                      <TH className="hidden text-right sm:table-cell">{t("duration")}</TH>
                    </tr>
                  </THead>
                  <TBody>
                    {caseResults.map((r, i) => (
                      <CaseRow key={`${r.name}-${i}`} result={r} />
                    ))}
                  </TBody>
                </Table>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

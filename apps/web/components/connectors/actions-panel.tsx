"use client";

import { Alert, Badge, Button, CodeBlock, ConfirmDialog, EmptyState, ErrorState, Field, SkeletonRows, Textarea, cn } from "@messer/ui";
import { useMutation } from "@tanstack/react-query";
import { Play, Zap } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { useRole } from "@/lib/hooks/use-me";

import { errorMessage, exampleArgs, useConnectionActions } from "./queries";
import type { ActionResponse, ActionSpec, Connection } from "./types";

export function ActionsPanel({ connection }: { connection: Connection }) {
  const t = useTranslations("connectors.actions");
  const tc = useTranslations("common");
  const canRun = useRole("builder");
  const actions = useConnectionActions(connection.id);
  const [selected, setSelected] = React.useState<ActionSpec | null>(null);
  const [argsText, setArgsText] = React.useState("{}");
  const [parseError, setParseError] = React.useState<string | null>(null);
  const [confirming, setConfirming] = React.useState(false);
  const current = selected ?? actions.data?.[0] ?? null;

  const choose = (action: ActionSpec) => {
    setSelected(action);
    setArgsText(JSON.stringify(exampleArgs(action.input_schema), null, 2));
    setParseError(null);
    run.reset();
  };

  React.useEffect(() => {
    if (!selected && actions.data && actions.data[0]) {
      setArgsText(JSON.stringify(exampleArgs(actions.data[0].input_schema), null, 2));
    }
  }, [actions.data, selected]);

  const run = useMutation({
    mutationFn: ({ action, args, confirm }: { action: ActionSpec; args: Record<string, unknown>; confirm: boolean }) =>
      http.post<ActionResponse>(`/connections/${connection.id}/actions/${action.name}`, { args, confirm }),
  });

  const parseArgs = (): Record<string, unknown> | null => {
    try {
      const parsed: unknown = JSON.parse(argsText || "{}");
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
      setParseError(null);
      return parsed as Record<string, unknown>;
    } catch {
      setParseError(t("invalidJson"));
      return null;
    }
  };

  const submit = () => {
    if (!current) return;
    const args = parseArgs();
    if (!args) return;
    if (current.side_effect) setConfirming(true);
    else run.mutate({ action: current, args, confirm: false });
  };

  if (actions.isLoading) return <SkeletonRows rows={4} />;
  if (actions.error) {
    return <ErrorState title={tc("errorTitle")} description={errorMessage(actions.error)} onRetry={() => void actions.refetch()} retryLabel={tc("retry")} />;
  }
  if ((actions.data ?? []).length === 0) return <EmptyState icon={<Zap />} title={t("empty")} />;

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
      <ul className="flex flex-col gap-1" aria-label={t("select")}>
        {(actions.data ?? []).map((a) => (
          <li key={a.name}>
            <button
              type="button"
              onClick={() => choose(a)}
              aria-current={current?.name === a.name}
              className={cn(
                "flex w-full flex-col items-start gap-0.5 rounded-md border px-3 py-2 text-left text-sm transition-colors",
                current?.name === a.name ? "border-fg bg-subtle" : "border-border bg-surface hover:bg-subtle",
              )}
            >
              <span className="flex w-full items-center justify-between gap-2">
                <span className="font-medium text-fg">{a.title}</span>
                <Badge tone={a.side_effect ? "warning" : "neutral"}>{a.side_effect ? t("sideEffect") : t("readOnly")}</Badge>
              </span>
              <span className="font-mono text-[11px] text-fg-subtle">{a.name}</span>
            </button>
          </li>
        ))}
      </ul>
      {current ? (
        <div className="flex min-w-0 flex-col gap-3">
          <div>
            <h3 className="text-base font-semibold">{current.title}</h3>
            <p className="text-sm text-fg-muted">{current.description}</p>
          </div>
          {current.side_effect ? <Alert tone="warning">{t("sideEffectHint")}</Alert> : null}
          <Field label={t("arguments")} htmlFor="action-args" error={parseError ?? undefined}>
            <Textarea
              id="action-args"
              rows={8}
              spellCheck={false}
              className="font-mono text-xs"
              value={argsText}
              onChange={(e) => setArgsText(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  submit();
                }
              }}
            />
          </Field>
          <details className="text-xs text-fg-muted">
            <summary className="cursor-pointer select-none">{t("schema")}</summary>
            <CodeBlock code={JSON.stringify(current.input_schema, null, 2)} language="json" className="mt-2" />
          </details>
          {canRun ? (
            <div>
              <Button variant="primary" onClick={submit} loading={run.isPending}>
                <Play />
                {t("run")}
              </Button>
            </div>
          ) : null}
          {run.error ? <Alert tone="danger">{errorMessage(run.error)}</Alert> : null}
          {run.data ? (
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2 text-xs text-fg-subtle">
                <span className="font-medium uppercase tracking-wide">{t("result")}</span>
                <span className="tabular">{t("elapsed", { ms: run.data.elapsed_ms })}</span>
                {run.data.demo ? <Badge tone="info">{t("demoResult")}</Badge> : null}
              </div>
              <CodeBlock code={JSON.stringify(run.data.result, null, 2)} language="json" className="max-h-[32rem] overflow-auto" />
            </div>
          ) : null}
        </div>
      ) : null}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("confirmTitle", { title: current?.title ?? "" })}
        description={t("confirmDescription", { connector: connection.connector_name })}
        confirmLabel={t("confirm")}
        cancelLabel={tc("cancel")}
        loading={run.isPending}
        onConfirm={() => {
          const args = parseArgs();
          if (current && args) run.mutate({ action: current, args, confirm: true }, { onSettled: () => setConfirming(false) });
        }}
      />
    </div>
  );
}

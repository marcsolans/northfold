"use client";

import { Alert, Badge, Button, Input, Kbd, StatusDot, type StatusTone, Switch, Textarea, cn } from "@messer/ui";
import { ExternalLink, Play, RotateCcw, Square, X } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { DecisionPanel } from "@/components/approvals/decision-panel";
import { JsonView } from "@/components/studio/json-view";
import { formatDuration, formatUsd, localeTag } from "@/lib/format";
import { useMe } from "@/lib/hooks/use-me";
import { ROLE_RANK } from "@/lib/types";
import type { DecisionBody } from "@/lib/studio/types";
import { durationOf, type RunState } from "@/lib/workflows/run";
import type { NodeRunStatus, WorkflowConfig, WorkflowInput } from "@/lib/workflows/types";

const PHASE_TONE: Record<RunState["phase"], StatusTone> = {
  idle: "neutral",
  running: "info",
  paused: "warning",
  success: "success",
  error: "danger",
  cancelled: "neutral",
};

const NODE_TONE: Record<NodeRunStatus, StatusTone> = {
  idle: "neutral",
  running: "info",
  success: "success",
  error: "danger",
  paused: "warning",
  skipped: "neutral",
};

function initialValue(input: WorkflowInput): string {
  if (input.type === "boolean") return "false";
  if (input.type === "object") return "{}";
  return "";
}

function parseValue(input: WorkflowInput, raw: string): { value: unknown; error: boolean } {
  if (input.type === "number") {
    if (raw.trim() === "") return { value: undefined, error: input.required };
    const n = Number(raw);
    return { value: n, error: !Number.isFinite(n) };
  }
  if (input.type === "boolean") return { value: raw === "true", error: false };
  if (input.type === "object") {
    if (!raw.trim()) return { value: undefined, error: input.required };
    try {
      return { value: JSON.parse(raw), error: false };
    } catch {
      return { value: undefined, error: true };
    }
  }
  if (!raw && input.required) return { value: undefined, error: true };
  return { value: raw === "" ? undefined : raw, error: false };
}

/** Input form → live run (node statuses on the canvas) → inline approvals → per-node detail. */
export function RunPanel({
  projectId,
  config,
  run,
  busy,
  deciding,
  canRun,
  dirty,
  selectedNode,
  onSelectNode,
  onRun,
  onStop,
  onReset,
  onDecide,
  onClose,
}: {
  projectId: string;
  config: WorkflowConfig | null;
  run: RunState;
  busy: boolean;
  deciding: string | null;
  canRun: boolean;
  dirty: boolean;
  selectedNode: string | null;
  onSelectNode: (id: string | null) => void;
  onRun: (input: Record<string, unknown>, event: Record<string, unknown> | null) => void;
  onStop: () => void;
  onReset: () => void;
  onDecide: (approvalId: string, body: DecisionBody) => void;
  onClose: () => void;
}) {
  const t = useTranslations("workflows.run");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const me = useMe();
  const inputs = React.useMemo(() => config?.inputs ?? [], [config]);
  const [values, setValues] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(inputs.map((i) => [i.name, initialValue(i)])),
  );
  const [eventEnabled, setEventEnabled] = React.useState(false);
  const [eventText, setEventText] = React.useState('{\n  "type": "webhook",\n  "body": {}\n}');
  const [freeInput, setFreeInput] = React.useState("{}");

  const parsed = inputs.map((i) => ({ input: i, ...parseValue(i, values[i.name] ?? "") }));
  let eventValue: Record<string, unknown> | null = null;
  let eventError = false;
  if (eventEnabled) {
    try {
      const raw: unknown = JSON.parse(eventText);
      if (raw && typeof raw === "object" && !Array.isArray(raw)) eventValue = raw as Record<string, unknown>;
      else eventError = true;
    } catch {
      eventError = true;
    }
  }
  let freeValue: Record<string, unknown> = {};
  let freeError = false;
  if (!config) {
    try {
      const raw: unknown = JSON.parse(freeInput || "{}");
      if (raw && typeof raw === "object" && !Array.isArray(raw)) freeValue = raw as Record<string, unknown>;
      else freeError = true;
    } catch {
      freeError = true;
    }
  }
  const invalid = parsed.some((p) => p.error) || eventError || freeError;

  const submit = () => {
    if (invalid || busy || !canRun) return;
    const input = config
      ? Object.fromEntries(parsed.filter((p) => p.value !== undefined).map((p) => [p.input.name, p.value]))
      : freeValue;
    onRun(input, eventValue);
  };
  const submitRef = React.useRef(submit);
  React.useEffect(() => {
    submitRef.current = submit;
  });
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        submitRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const nodeIds = config ? config.nodes.map((n) => n.id) : Object.keys(run.nodes);
  const detail = selectedNode ? run.nodes[selectedNode] : undefined;
  const role = me.data?.active_org?.role;
  const canDecide = (assigned: string) =>
    Boolean(me.data?.is_superadmin) || (role ? ROLE_RANK[role] >= (ROLE_RANK[assigned as keyof typeof ROLE_RANK] ?? 3) : false);
  const lastRunId = run.runIds[run.runIds.length - 1];

  return (
    <aside className="flex w-[24rem] shrink-0 flex-col border-l border-border bg-bg" aria-label={t("title")}>
      <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <Play className="size-4 text-fg-muted" aria-hidden />
        <p className="flex-1 text-sm font-semibold">{t("title")}</p>
        <Button variant="ghost" size="icon-sm" aria-label={tc("close")} onClick={onClose}>
          <X />
        </Button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
        {dirty ? <Alert tone="warning">{t("unsavedHint")}</Alert> : null}
        <form
          className="space-y-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          {config ? (
            inputs.length === 0 ? (
              <p className="text-xs text-fg-subtle">{t("noInputs")}</p>
            ) : (
              parsed.map(({ input, error }) => (
                <div key={input.name} className="space-y-1">
                  <label htmlFor={`run-${input.name}`} className="flex items-center gap-1.5 text-xs font-medium">
                    <code className="font-mono">{input.name}</code>
                    {input.required ? <span className="text-danger">*</span> : null}
                    <span className="font-normal text-fg-subtle">{t(`types.${input.type}`)}</span>
                  </label>
                  {input.type === "boolean" ? (
                    <Switch
                      id={`run-${input.name}`}
                      checked={values[input.name] === "true"}
                      onCheckedChange={(v) => setValues((s) => ({ ...s, [input.name]: v ? "true" : "false" }))}
                    />
                  ) : input.type === "object" ? (
                    <Textarea
                      id={`run-${input.name}`}
                      rows={3}
                      className="font-mono text-xs"
                      value={values[input.name] ?? ""}
                      aria-invalid={error || undefined}
                      onChange={(e) => setValues((s) => ({ ...s, [input.name]: e.target.value }))}
                    />
                  ) : (
                    <Input
                      id={`run-${input.name}`}
                      type={input.type === "number" ? "number" : "text"}
                      value={values[input.name] ?? ""}
                      aria-invalid={error || undefined}
                      onChange={(e) => setValues((s) => ({ ...s, [input.name]: e.target.value }))}
                    />
                  )}
                  {input.description ? <p className="text-[11px] text-fg-subtle">{input.description}</p> : null}
                </div>
              ))
            )
          ) : (
            <div className="space-y-1">
              <label htmlFor="run-free-input" className="text-xs font-medium">
                {t("jsonInput")}
              </label>
              <Textarea id="run-free-input" rows={4} className="font-mono text-xs" value={freeInput} aria-invalid={freeError || undefined}
                onChange={(e) => setFreeInput(e.target.value)} />
            </div>
          )}
          <div className="space-y-1.5 rounded-md border border-border p-2">
            <label className="flex items-center justify-between gap-2 text-xs font-medium">
              {t("sampleEvent")}
              <Switch checked={eventEnabled} onCheckedChange={setEventEnabled} aria-label={t("sampleEvent")} />
            </label>
            <p className="text-[11px] text-fg-subtle">{t("sampleEventHint")}</p>
            {eventEnabled ? (
              <Textarea rows={5} className="font-mono text-xs" value={eventText} aria-invalid={eventError || undefined}
                onChange={(e) => setEventText(e.target.value)} aria-label={t("sampleEvent")} />
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            {busy && run.phase === "running" ? (
              <Button type="button" variant="secondary" size="sm" onClick={onStop}>
                <Square />
                {t("stop")}
              </Button>
            ) : (
              <Button type="submit" variant="primary" size="sm" disabled={!canRun || invalid || busy}>
                <Play />
                {t("run")}
                <Kbd className="border-accent-fg/30 bg-transparent text-accent-fg">⌘↵</Kbd>
              </Button>
            )}
            {run.phase !== "idle" && !busy ? (
              <Button type="button" variant="ghost" size="sm" onClick={onReset}>
                <RotateCcw />
                {t("clear")}
              </Button>
            ) : null}
          </div>
          {!canRun ? <p className="text-xs text-fg-subtle">{t("viewerHint")}</p> : null}
        </form>

        {run.phase !== "idle" ? (
          <section className="space-y-2" aria-live="polite">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={PHASE_TONE[run.phase] === "neutral" ? "neutral" : PHASE_TONE[run.phase]}>
                <StatusDot tone={PHASE_TONE[run.phase]} pulse={run.phase === "running"} />
                {t(`phase.${run.phase}`)}
              </Badge>
              {run.durationMs ? <span className="text-xs tabular text-fg-muted">{formatDuration(run.durationMs)}</span> : null}
              {run.phase !== "running" ? <span className="text-xs tabular text-fg-muted">{formatUsd(run.costUsd, locale)}</span> : null}
              {run.demo ? <Badge tone="info">{t("demo")}</Badge> : null}
              {lastRunId ? (
                <Link className="ml-auto inline-flex items-center gap-1 text-xs text-fg-muted hover:text-fg" href={`/app/projects/${projectId}/traces/${lastRunId}`}>
                  {t("trace")}
                  <ExternalLink className="size-3" aria-hidden />
                </Link>
              ) : null}
            </div>
            {run.error ? (
              <Alert tone="danger" title={t("errorTitle")}>
                {run.error.message ?? t("errorGeneric")}
              </Alert>
            ) : null}
            {run.phase === "paused"
              ? run.approvals.map((approval) => (
                  <div key={approval.id} className="space-y-2 rounded-md border border-warning/40 bg-warning-soft/40 p-2.5">
                    <p className="text-xs font-semibold text-fg">{t("approvalTitle")}</p>
                    <p className="text-sm">{approval.title}</p>
                    <p className="text-[11px] text-fg-subtle">{t("approvalNode", { node: approval.tool_name })}</p>
                    <DecisionPanel
                      idPrefix={`wf-approval-${approval.id}`}
                      payload={approval.payload}
                      schema={null}
                      canDecide={canDecide(approval.assigned_role)}
                      assignedRole={approval.assigned_role}
                      busy={deciding === approval.id ? "approve" : null}
                      onDecide={(body) => onDecide(approval.id, body)}
                    />
                  </div>
                ))
              : null}
            <ol className="divide-y divide-border rounded-md border border-border">
              {nodeIds.map((id) => {
                const n = run.nodes[id];
                const status = n?.status ?? "idle";
                const duration = durationOf(n);
                return (
                  <li key={id}>
                    <button
                      type="button"
                      onClick={() => onSelectNode(selectedNode === id ? null : id)}
                      aria-pressed={selectedNode === id}
                      className={cn("flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs hover:bg-subtle", selectedNode === id && "bg-subtle")}
                    >
                      <StatusDot tone={NODE_TONE[status]} pulse={status === "running"} />
                      <code className="min-w-0 flex-1 truncate font-mono">{id}</code>
                      <span className="text-fg-subtle">{t(`status.${status}`)}</span>
                      <span className="w-14 text-right tabular text-fg-muted">{duration !== null ? formatDuration(duration) : ""}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
            {selectedNode && detail ? (
              <div className="space-y-2 rounded-md border border-border p-2.5">
                <div className="flex items-center gap-2">
                  <code className="flex-1 font-mono text-xs font-semibold">{selectedNode}</code>
                  {detail.replayed ? <Badge tone="info">{t("replayed")}</Badge> : null}
                  {detail.iterations > 1 ? <Badge tone="outline">{t("iterations", { n: detail.iterations })}</Badge> : null}
                </div>
                <dl className="grid grid-cols-2 gap-1 text-xs">
                  <dt className="text-fg-subtle">{t("duration")}</dt>
                  <dd className="tabular">{formatDuration(durationOf(detail))}</dd>
                  <dt className="text-fg-subtle">{t("cost")}</dt>
                  <dd className="tabular">{detail.costUsd !== undefined ? formatUsd(detail.costUsd, locale) : "—"}</dd>
                </dl>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">{t("input")}</p>
                <JsonView value={detail.input ?? null} defaultDepth={2} />
                <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">{t("output")}</p>
                <JsonView value={detail.output ?? null} defaultDepth={2} />
                {detail.error ? (
                  <>
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-danger">{t("error")}</p>
                    <JsonView value={detail.error} defaultDepth={1} />
                  </>
                ) : null}
              </div>
            ) : selectedNode ? (
              <p className="text-xs text-fg-subtle">{t("nodeNotRun")}</p>
            ) : null}
            {run.phase === "success" ? (
              <div className="space-y-1">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">{t("result")}</p>
                <JsonView value={run.output ?? null} defaultDepth={3} />
              </div>
            ) : null}
          </section>
        ) : (
          <p className="text-xs text-fg-subtle">{t("idleHint")}</p>
        )}
      </div>
    </aside>
  );
}

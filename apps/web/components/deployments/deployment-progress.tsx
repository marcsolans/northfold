"use client";

import { Alert, Badge, Button, ErrorState, Skeleton, Spinner, cn, toast } from "@messer/ui";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleSlash,
  ExternalLink,
  Info,
  Loader2,
  X,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { projectHref } from "@/components/shell/nav-config";
import { ENABLED_PROJECT_TABS } from "@/components/studio/project-tabs";
import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { sameId, shortHash } from "@/lib/studio/format";
import { useEvalRuns, useMembers } from "@/lib/studio/hooks";
import type { EvalRun, MemberKind } from "@/lib/studio/types";

import { DeploymentStatusBadge, ForcedBadge, useEnvironmentLabel } from "./labels";
import { useDeployment, useInvalidateDeployments, useMemberName } from "./queries";
import { type Deployment, type DeploymentLog, type GateResult, evalsSkipped, gateResults, isActive } from "./types";

type StepKey = "pending" | "evaluating" | "deploying" | "done";
type StepState = "done" | "current" | "failed" | "upcoming";

const STEPS: StepKey[] = ["pending", "evaluating", "deploying", "done"];
const STEP_INDEX: Record<string, number> = { pending: 0, evaluating: 1, deploying: 2, live: 3, superseded: 3, rolled_back: 3 };

function stepStates(dep: Deployment, gate: GateResult[]): Record<StepKey, StepState> {
  if (dep.status === "failed") {
    const gateFailed = gate.some((g) => (g.failed ?? 0) > 0);
    return {
      pending: "done",
      evaluating: gateFailed ? "failed" : "done",
      deploying: gateFailed ? "upcoming" : "failed",
      done: "failed",
    };
  }
  const current = STEP_INDEX[dep.status] ?? 0;
  const active = isActive(dep.status);
  const state = (i: number): StepState => (i < current ? "done" : i === current ? (active ? "current" : "done") : "upcoming");
  return { pending: state(0), evaluating: state(1), deploying: state(2), done: state(3) };
}

function StepIcon({ state, index }: { state: StepState; index: number }) {
  const base = "flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold";
  if (state === "done") return <span className={cn(base, "border-success bg-success text-white")}><Check className="size-3.5" strokeWidth={3} aria-hidden /></span>;
  if (state === "failed") return <span className={cn(base, "border-danger bg-danger text-white")}><X className="size-3.5" strokeWidth={3} aria-hidden /></span>;
  if (state === "current") return <span className={cn(base, "border-info bg-info-soft text-info")}><Loader2 className="size-3.5 animate-spin" aria-hidden /></span>;
  return <span className={cn(base, "tabular border-border-strong bg-surface text-fg-subtle")}>{index + 1}</span>;
}

export function DeploymentStepper({ deployment }: { deployment: Deployment }) {
  const t = useTranslations("deployments.progress");
  const gate = gateResults(deployment.logs);
  const states = stepStates(deployment, gate);
  const skipped = evalsSkipped(deployment.logs);
  const label = (key: StepKey): string => {
    if (key === "evaluating" && skipped) return t("steps.evalsSkipped");
    if (key === "done") return deployment.status === "failed" ? t("steps.failed") : t("steps.live");
    return t(`steps.${key}`);
  };
  return (
    <ol aria-label={t("stepsLabel")} className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-0">
      {STEPS.map((key, i) => {
        const state = states[key];
        return (
          <li
            key={key}
            aria-current={state === "current" ? "step" : undefined}
            className="flex items-center gap-2 sm:flex-1 sm:last:flex-none"
          >
            <StepIcon state={state} index={i} />
            <span
              className={cn(
                "whitespace-nowrap text-sm",
                state === "upcoming" ? "text-fg-subtle" : "font-medium text-fg",
                state === "failed" && "text-danger",
              )}
            >
              {label(key)}
              <span className="sr-only"> — {t(`stepState.${state}`)}</span>
            </span>
            {i < STEPS.length - 1 ? (
              <span
                aria-hidden
                className={cn("mx-3 hidden h-px flex-1 sm:block", state === "done" ? "bg-success" : "bg-border")}
              />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function memberHref(projectId: string, name: string, kind: MemberKind | undefined): string | null {
  if (kind === "workflow") {
    return ENABLED_PROJECT_TABS.includes("workflows")
      ? `${projectHref(projectId, "workflows")}/${encodeURIComponent(name)}`
      : null;
  }
  return `${projectHref(projectId, "agents")}/${encodeURIComponent(name)}`;
}

/** The deploy-triggered eval run of this member for this deployment. */
function findDeployRun(runs: EvalRun[] | undefined, dep: Deployment): EvalRun | undefined {
  if (!runs) return undefined;
  const deploys = runs.filter((r) => r.trigger === "deploy");
  const exact = deploys.find((r) => sameId(r.id, dep.eval_run_id));
  if (exact) return exact;
  const from = new Date(dep.created_at).getTime() - 1000;
  const to = (dep.finished_at ? new Date(dep.finished_at).getTime() : Date.now()) + 5000;
  return deploys.find((r) => {
    const at = new Date(r.created_at).getTime();
    return at >= from && at <= to;
  });
}

function caseError(error: unknown): string {
  if (!error) return "";
  if (typeof error === "string") return error;
  const e = error as { message?: unknown; type?: unknown };
  if (typeof e.message === "string") return typeof e.type === "string" ? `${e.type}: ${e.message}` : e.message;
  try {
    return JSON.stringify(error).slice(0, 300);
  } catch {
    return "";
  }
}

function GateCases({ projectId, member, deployment }: { projectId: string; member: string; deployment: Deployment }) {
  const t = useTranslations("deployments.gate");
  const tc = useTranslations("common");
  const runs = useEvalRuns(projectId, member);
  if (runs.isLoading) return <Skeleton className="h-12 w-full" />;
  if (runs.error) {
    return <ErrorState title={tc("errorTitle")} description={t("casesError")} onRetry={() => void runs.refetch()} retryLabel={tc("retry")} />;
  }
  const run = findDeployRun(runs.data, deployment);
  if (!run) return <p className="text-xs text-fg-subtle">{t("casesMissing")}</p>;
  const cases = run.results.filter((r) => r.name !== undefined || r.passed !== undefined);
  const runError = run.results.find((r) => r.error && r.name === undefined)?.error;
  return (
    <div className="flex flex-col gap-2">
      {runError ? <Alert tone="danger">{caseError(runError)}</Alert> : null}
      {cases.length === 0 ? (
        runError ? null : <p className="text-xs text-fg-subtle">{t("noCases")}</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded-md border border-border bg-surface">
          {cases.map((c, i) => (
            <li key={`${c.name ?? "case"}-${i}`} className="flex items-start gap-2 px-3 py-2 text-xs">
              {c.passed ? (
                <CheckCircle2 className="mt-px size-4 shrink-0 text-success" aria-label={t("pass")} />
              ) : (
                <XCircle className="mt-px size-4 shrink-0 text-danger" aria-label={t("fail")} />
              )}
              <div className="min-w-0">
                <p className="font-mono font-medium">{c.name ?? t("unnamedCase")}</p>
                {c.error ? <p className="break-words text-danger">{caseError(c.error)}</p> : null}
                {!c.error && !c.passed && c.validators?.length ? (
                  <p className="text-fg-muted">
                    {t("validatorsFailed", { names: c.validators.filter((v) => !v.passed).map((v) => v.name).join(", ") })}
                  </p>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function GateRow({
  projectId,
  result,
  kind,
  deployment,
}: {
  projectId: string;
  result: GateResult;
  kind: MemberKind | undefined;
  deployment: Deployment;
}) {
  const t = useTranslations("deployments.gate");
  const failed = (result.failed ?? 0) > 0;
  const [open, setOpen] = React.useState(failed);
  const href = memberHref(projectId, result.member, kind);
  const hasEvals = result.passed !== null;
  return (
    <li className="flex flex-col gap-2 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        {hasEvals ? (
          <button
            type="button"
            className="rounded-sm p-0.5 hover:bg-muted"
            aria-expanded={open}
            aria-label={t("toggleCases", { member: result.member })}
            onClick={() => setOpen((o) => !o)}
          >
            <ChevronRight className={cn("size-4 transition-transform", open && "rotate-90")} aria-hidden />
          </button>
        ) : (
          <span className="inline-block size-5" aria-hidden />
        )}
        {!hasEvals ? (
          <CircleSlash className="size-4 text-warning" aria-hidden />
        ) : failed ? (
          <XCircle className="size-4 text-danger" aria-hidden />
        ) : (
          <CheckCircle2 className="size-4 text-success" aria-hidden />
        )}
        <span className="font-mono text-sm font-medium">{result.member}</span>
        {kind ? <Badge tone="outline">{t(`kind.${kind}`)}</Badge> : null}
        <span className="tabular text-xs text-fg-muted">
          {hasEvals ? t("counts", { passed: result.passed ?? 0, failed: result.failed ?? 0 }) : t("noEvals")}
        </span>
        {href ? (
          <Link href={href} className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline">
            {t("viewEvals")}
            <ExternalLink className="size-3" aria-hidden />
          </Link>
        ) : null}
      </div>
      {open && hasEvals ? (
        <div className="pl-7">
          <GateCases projectId={projectId} member={result.member} deployment={deployment} />
        </div>
      ) : null}
    </li>
  );
}

export function GateResults({ projectId, deployment }: { projectId: string; deployment: Deployment }) {
  const t = useTranslations("deployments.gate");
  const members = useMembers(projectId);
  const kinds = React.useMemo(() => new Map((members.data ?? []).map((m) => [m.name, m.kind])), [members.data]);
  const results = gateResults(deployment.logs);
  const failed = results.filter((r) => (r.failed ?? 0) > 0);
  const waiting = results.length === 0 && (deployment.status === "pending" || deployment.status === "evaluating");

  let body: React.ReactNode;
  if (evalsSkipped(deployment.logs)) {
    body = <Alert tone="info">{t("skipped")}</Alert>;
  } else if (waiting) {
    body = (
      <p className="flex items-center gap-2 text-sm text-fg-muted">
        <Spinner className="size-3.5" label={t("running")} />
        {deployment.status === "pending" ? t("queued") : t("running")}
      </p>
    );
  } else if (results.length === 0) {
    body = <p className="text-sm text-fg-muted">{t("noMembers")}</p>;
  } else {
    body = (
      <ul className="divide-y divide-border rounded-md border border-border">
        {results.map((r) => (
          <GateRow key={r.member} projectId={projectId} result={r} kind={kinds.get(r.member)} deployment={deployment} />
        ))}
      </ul>
    );
  }

  return (
    <section aria-labelledby={`gate-${deployment.id}`} className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <h4 id={`gate-${deployment.id}`} className="text-sm font-semibold">
          {t("title")}
        </h4>
        {results.length > 0 && !evalsSkipped(deployment.logs) ? (
          failed.length > 0 ? (
            <Badge tone="danger">{t("summaryFailed", { count: failed.length })}</Badge>
          ) : (
            <Badge tone="success">{t("summaryPassed")}</Badge>
          )
        ) : null}
      </div>
      {failed.length > 0 && deployment.forced && deployment.status !== "failed" ? (
        <Alert tone="warning">{t("forcedThrough")}</Alert>
      ) : null}
      {failed.length > 0 && deployment.status === "failed" ? <Alert tone="danger">{t("blocked")}</Alert> : null}
      {body}
    </section>
  );
}

const LEVEL_STYLE: Record<string, { icon: React.ReactNode; className: string }> = {
  info: { icon: <Info className="size-3.5 text-fg-subtle" aria-hidden />, className: "text-fg" },
  warning: { icon: <AlertTriangle className="size-3.5 text-warning" aria-hidden />, className: "text-warning" },
  error: { icon: <XCircle className="size-3.5 text-danger" aria-hidden />, className: "text-danger" },
};

export function DeploymentLogs({ deployment }: { deployment: Deployment }) {
  const t = useTranslations("deployments.progress");
  const locale = localeTag(useLocale());
  const ref = React.useRef<HTMLOListElement>(null);
  const stick = React.useRef(true);
  const count = deployment.logs.length;

  React.useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [count]);

  const time = (at: string) =>
    new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(at));

  return (
    <section className="flex flex-col gap-2" aria-labelledby={`logs-${deployment.id}`}>
      <h4 id={`logs-${deployment.id}`} className="text-sm font-semibold">
        {t("logs")}
      </h4>
      <ol
        ref={ref}
        role="log"
        aria-live="polite"
        aria-label={t("logs")}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }}
        className="max-h-64 overflow-y-auto rounded-md border border-border bg-subtle px-3 py-2 font-mono text-xs leading-relaxed"
      >
        {deployment.logs.length === 0 ? <li className="text-fg-subtle">{t("noLogs")}</li> : null}
        {deployment.logs.map((entry: DeploymentLog, i) => {
          const style = LEVEL_STYLE[entry.level] ?? LEVEL_STYLE.info!;
          return (
            <li key={`${entry.at}-${i}`} className="flex items-start gap-2 py-0.5">
              <time dateTime={entry.at} className="tabular shrink-0 text-fg-subtle">
                {time(entry.at)}
              </time>
              <span className="mt-0.5 shrink-0">{style.icon}</span>
              <span className={cn("min-w-0 break-words", style.className)}>
                <span className="sr-only">{t.has(`level.${entry.level}`) ? t(`level.${entry.level}`) : entry.level}: </span>
                {entry.message}
              </span>
            </li>
          );
        })}
        {isActive(deployment.status) ? (
          <li className="flex items-center gap-2 py-0.5 text-fg-subtle">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            {t("inProgress")}
          </li>
        ) : null}
      </ol>
    </section>
  );
}

/** Header line of a deployment: environment, version, commit, who and when. */
export function DeploymentSummary({ deployment }: { deployment: Deployment }) {
  const t = useTranslations("deployments.progress");
  const locale = localeTag(useLocale());
  const envLabel = useEnvironmentLabel();
  const memberName = useMemberName();
  const who = memberName(deployment.created_by);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">
          {t("title", { environment: envLabel(deployment.environment), version: deployment.version ?? "—" })}
        </span>
        <DeploymentStatusBadge status={deployment.status} />
        {deployment.forced ? <ForcedBadge /> : null}
      </div>
      <p className="text-xs text-fg-muted">
        <span className="font-mono">{shortHash(deployment.git_commit)}</span>
        {deployment.message ? <> · {deployment.message}</> : null}
        {" · "}
        <time dateTime={deployment.created_at} title={formatDate(deployment.created_at, locale, true)}>
          {formatRelative(deployment.created_at, locale)}
        </time>
        {who ? <> · {t("by", { name: who })}</> : null}
      </p>
    </div>
  );
}

/**
 * Live view of one deployment: status stepper, evals gate per member and the log stream. Polls every 2 s while the
 * deployment is pending, evaluating or deploying; when it settles, environments and history are refreshed.
 */
export function DeploymentProgress({
  projectId,
  deployment: initial,
  notify = false,
  onDismiss,
}: {
  projectId: string;
  deployment: Deployment;
  notify?: boolean;
  onDismiss?: () => void;
}) {
  const t = useTranslations("deployments.progress");
  const tc = useTranslations("common");
  const envLabel = useEnvironmentLabel();
  const query = useDeployment(initial.id, initial);
  const invalidate = useInvalidateDeployments(projectId);
  const dep = query.data ?? initial;
  const previous = React.useRef(dep.status);

  React.useEffect(() => {
    const before = previous.current;
    previous.current = dep.status;
    if (before === dep.status || !isActive(before) || isActive(dep.status)) return;
    invalidate();
    if (!notify) return;
    if (dep.status === "live") {
      toast.success(t("liveToast", { environment: envLabel(dep.environment), version: dep.version ?? "—" }));
    } else if (dep.status === "failed") {
      toast.error(t("failedToast", { environment: envLabel(dep.environment) }));
    }
  }, [dep.status, dep.environment, dep.version, invalidate, notify, t, envLabel]);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <DeploymentSummary deployment={dep} />
        {onDismiss && !isActive(dep.status) ? (
          <Button variant="ghost" size="icon-sm" aria-label={tc("close")} onClick={onDismiss}>
            <X />
          </Button>
        ) : null}
      </div>
      {query.error ? (
        <ErrorState title={tc("errorTitle")} description={t("pollError")} onRetry={() => void query.refetch()} retryLabel={tc("retry")} />
      ) : null}
      <DeploymentStepper deployment={dep} />
      <GateResults projectId={projectId} deployment={dep} />
      <DeploymentLogs deployment={dep} />
    </div>
  );
}

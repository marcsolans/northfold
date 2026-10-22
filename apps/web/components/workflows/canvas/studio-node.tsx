"use client";

import { StatusDot, type StatusTone, cn } from "@messer/ui";
import { Handle, type Node, type NodeProps, Position } from "@xyflow/react";
import { AlertTriangle, History } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import type { NodeRun, NodeRunStatus, WorkflowNode } from "@/lib/workflows/types";

import { FALLBACK_ICON, NODE_ICONS } from "../node-meta";

export interface StudioNodeData extends Record<string, unknown> {
  node: WorkflowNode;
  summary: string;
  issues: string[];
  run?: NodeRun;
  details?: string;
  isBody: boolean;
  readOnly: boolean;
  /** Code mode: a step introspected from workflow.py (no Studio type). */
  engineKind?: string;
}

export type StudioFlowNode = Node<StudioNodeData, "studio">;

const RUN_TONE: Record<NodeRunStatus, StatusTone> = {
  idle: "neutral",
  running: "info",
  success: "success",
  error: "danger",
  paused: "warning",
  skipped: "neutral",
};

const RUN_RING: Record<NodeRunStatus, string> = {
  idle: "",
  running: "border-info ring-2 ring-info/25",
  success: "border-success ring-1 ring-success/25",
  error: "border-danger ring-2 ring-danger/25",
  paused: "border-warning ring-2 ring-warning/30",
  skipped: "border-dashed opacity-60",
};

const handleClass = "!size-2.5 !rounded-full !border !border-border-strong !bg-surface";

function StudioNodeView({ data, selected }: NodeProps<StudioFlowNode>) {
  const t = useTranslations("workflows");
  const { node, run } = data;
  const Icon = NODE_ICONS[node.type] ?? FALLBACK_ICON;
  const status = run?.status ?? "idle";
  const hasIssues = data.issues.length > 0;
  const typeLabel = data.engineKind ? t(`canvas.engineKinds.${data.engineKind === "agent" || data.engineKind === "workflow" ? data.engineKind : "tool"}`) : t(`nodeTypes.${node.type}.label`);
  return (
    <div
      className={cn(
        "w-56 rounded-md border border-border bg-surface text-left shadow-sm transition-colors",
        data.isBody && "border-dashed",
        RUN_RING[status],
        hasIssues && "border-danger",
        selected && "outline outline-2 outline-offset-2 outline-fg/60",
      )}
      title={hasIssues ? data.issues.join("\n") : undefined}
    >
      {node.type !== "input" ? (
        <Handle type="target" position={Position.Left} className={handleClass} isConnectable={!data.readOnly} />
      ) : null}
      <div className="flex items-start gap-2 px-2.5 py-2">
        <span
          className={cn(
            "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-sm border border-border bg-subtle text-fg-muted",
            node.type === "approval" && "border-accent/30 bg-accent-soft text-accent",
          )}
          aria-hidden
        >
          <Icon className="size-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold leading-5 text-fg">{node.label || node.id}</p>
          <p className="truncate font-mono text-[11px] leading-4 text-fg-subtle">
            {node.id} · {typeLabel}
          </p>
        </div>
        {hasIssues ? <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-danger" aria-label={t("canvas.nodeHasIssues")} /> : null}
        {run && status !== "idle" ? (
          <StatusDot tone={RUN_TONE[status]} pulse={status === "running"} className="mt-1.5" />
        ) : null}
      </div>
      {data.summary ? (
        <p className="truncate border-t border-border px-2.5 py-1.5 font-mono text-[11px] text-fg-muted">{data.summary}</p>
      ) : null}
      {run && status !== "idle" ? (
        <div className="flex items-center justify-between gap-2 border-t border-border px-2.5 py-1 text-[11px] text-fg-muted">
          <span>{t(`run.status.${status}`)}</span>
          <span className="flex items-center gap-1 tabular">
            {run.replayed ? <History className="size-3" aria-label={t("run.replayed")} /> : null}
            {data.details}
          </span>
        </div>
      ) : null}
      {node.type === "condition" ? (
        <>
          <Handle id="true" type="source" position={Position.Right} style={{ top: "38%" }} className={cn(handleClass, "!bg-success")} isConnectable={!data.readOnly} />
          <Handle id="false" type="source" position={Position.Right} style={{ top: "72%" }} className={cn(handleClass, "!bg-danger")} isConnectable={!data.readOnly} />
          <span className="pointer-events-none absolute -right-7 top-[30%] text-[10px] font-medium text-success">{t("canvas.branchTrue")}</span>
          <span className="pointer-events-none absolute -right-7 top-[64%] text-[10px] font-medium text-danger">{t("canvas.branchFalse")}</span>
        </>
      ) : node.type !== "output" ? (
        <Handle type="source" position={Position.Right} className={handleClass} isConnectable={!data.readOnly} />
      ) : null}
      {node.type === "loop" ? (
        <Handle id="body" type="source" position={Position.Bottom} className={cn(handleClass, "!bg-info")} isConnectable={!data.readOnly} />
      ) : null}
    </div>
  );
}

export const StudioNode = React.memo(StudioNodeView);

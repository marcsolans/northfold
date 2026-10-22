"use client";

import "@xyflow/react/dist/style.css";

import { Alert } from "@messer/ui";
import { Background, BackgroundVariant, Controls, type Edge, MiniMap, type NodeChange, ReactFlow } from "@xyflow/react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import * as React from "react";

import type { RunState } from "@/lib/workflows/run";
import type { FlowGraph, NodeType, Position } from "@/lib/workflows/types";

import { type StudioFlowNode, StudioNode } from "./studio-node";

const nodeTypes = { studio: StudioNode };

function studioType(kind: string): NodeType {
  if (kind === "agent") return "agent";
  if (kind === "workflow") return "sub_workflow";
  return "custom";
}

/** Code mode: the graph the engine introspects from workflow.py (read-only; positions can still be arranged). */
export function EngineFlow({
  flow,
  error,
  positions,
  run,
  canArrange,
  onArrange,
  onSelect,
}: {
  flow: FlowGraph | null;
  error: string | null;
  positions: Record<string, Position>;
  run: RunState | null;
  canArrange: boolean;
  onArrange: (positions: Record<string, Position>) => void;
  onSelect: (stepName: string | null) => void;
}) {
  const t = useTranslations("workflows.canvas");
  const { resolvedTheme } = useTheme();
  const [local, setLocal] = React.useState<Record<string, Position>>(positions);
  const [measured, setMeasured] = React.useState<Record<string, { width: number; height: number }>>({});
  React.useEffect(() => setLocal(positions), [positions]);

  const nodes = React.useMemo<StudioFlowNode[]>(() => {
    if (!flow) return [];
    return flow.nodes.map((n, index) => {
      const step = n.id.split(".").slice(1).join(".") || n.id;
      const position = local[n.id] ?? n.position ?? { x: 80 + (index % 4) * 280, y: 80 + Math.floor(index / 4) * 140 };
      return {
        id: n.id,
        type: "studio" as const,
        position: position.x === 0 && position.y === 0 && !local[n.id] ? { x: 80 + (index % 4) * 280, y: 80 + Math.floor(index / 4) * 140 } : position,
        data: {
          node: { id: step, type: studioType(n.type), label: step, config: {} },
          summary: "",
          issues: [],
          run: run?.nodes[step],
          isBody: false,
          readOnly: true,
          engineKind: n.type,
        },
        measured: measured[n.id],
        draggable: canArrange,
        connectable: false,
        deletable: false,
      };
    });
  }, [flow, local, run, measured, canArrange]);

  const edges = React.useMemo<Edge[]>(
    () =>
      (flow?.edges ?? []).map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.when ? t("conditional") : undefined,
        style: e.kind === "param" ? { strokeDasharray: "4 4" } : undefined,
        deletable: false,
      })),
    [flow, t],
  );

  const onNodesChange = (changes: NodeChange<StudioFlowNode>[]) => {
    const dims: Record<string, { width: number; height: number }> = {};
    const moved: Record<string, Position> = {};
    for (const c of changes) {
      if (c.type === "dimensions" && c.dimensions) dims[c.id] = c.dimensions;
      if (c.type === "position" && c.position) moved[c.id] = c.position;
      if (c.type === "select" && c.selected) onSelect(c.id.split(".").slice(1).join(".") || c.id);
    }
    if (Object.keys(dims).length) setMeasured((m) => ({ ...m, ...dims }));
    if (Object.keys(moved).length) setLocal((p) => ({ ...p, ...moved }));
  };

  if (!flow) {
    return (
      <div className="p-6">
        <Alert tone="warning" title={t("flowUnavailable")}>
          {error ?? t("flowEmpty")}
        </Alert>
      </div>
    );
  }
  return (
    <div className="relative min-h-0 flex-1" aria-label={t("label")}>
      <ReactFlow<StudioFlowNode, Edge>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={() => onArrange(local)}
        onPaneClick={() => onSelect(null)}
        nodesConnectable={false}
        fitView
        colorMode={resolvedTheme === "dark" ? "dark" : "light"}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="var(--border-strong)" />
        <MiniMap pannable zoomable className="!rounded-md !border !border-border" ariaLabel={t("minimap")} />
        <Controls showInteractive={false} className="!rounded-md !border !border-border !shadow-none" />
      </ReactFlow>
    </div>
  );
}

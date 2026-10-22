"use client";

import "@xyflow/react/dist/style.css";

import { Button, Tooltip, cn, toast } from "@messer/ui";
import {
  Background,
  BackgroundVariant,
  type Connection,
  Controls,
  type Edge,
  type EdgeChange,
  MiniMap,
  type NodeChange,
  Panel,
  ReactFlow,
  type Viewport as RFViewport,
  type XYPosition,
  useReactFlow,
} from "@xyflow/react";
import {
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignHorizontalJustifyStart,
  AlignHorizontalSpaceAround,
  AlignVerticalJustifyStart,
  AlignVerticalSpaceAround,
  ClipboardPaste,
  Copy,
  CopyPlus,
  Grid3x3,
  Maximize,
  Redo2,
  Trash2,
  Undo2,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import * as React from "react";

import { formatDuration, formatUsd, localeTag } from "@/lib/format";
import {
  addEdge,
  bodyOf,
  createsCycle,
  duplicate,
  isLoopEdge,
  nextBranch,
  removeNodes,
  uniqueId,
} from "@/lib/workflows/graph";
import type { History } from "@/lib/workflows/history";
import { durationOf, type RunState } from "@/lib/workflows/run";
import type {
  CustomFunction,
  NodeType,
  Palette,
  Viewport,
  WorkflowConfig,
  WorkflowEdge,
  WorkflowNode,
} from "@/lib/workflows/types";

import { DRAG_MIME, type DragPayload, nodeSummary } from "../node-meta";
import { NodePalette } from "./node-palette";
import { type StudioFlowNode, StudioNode } from "./studio-node";

const nodeTypes = { studio: StudioNode };
const GRID: [number, number] = [16, 16];
const DEFAULT_SIZE = { width: 224, height: 80 };

export function edgeId(e: WorkflowEdge): string {
  return `${e.source}->${e.target}`;
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    Boolean(target.closest(".monaco-editor, [role='dialog'], [role='listbox'], [role='menu']"))
  );
}

export interface CanvasProps {
  doc: WorkflowConfig;
  history: History<WorkflowConfig>;
  palette: Palette;
  functions: CustomFunction[];
  selected: string[];
  onSelect: (ids: string[]) => void;
  issuesByNode: Map<string, string[]>;
  issueEdges: Set<string>;
  run: RunState | null;
  readOnly: boolean;
  viewport: Viewport;
  onViewportChange: (viewport: Viewport) => void;
}

export function WorkflowCanvas(props: CanvasProps) {
  const { doc, history, palette, functions, selected, onSelect, issuesByNode, issueEdges, run, readOnly } = props;
  const t = useTranslations("workflows");
  const locale = localeTag(useLocale());
  const { resolvedTheme } = useTheme();
  const rf = useReactFlow<StudioFlowNode, Edge>();
  const wrapper = React.useRef<HTMLDivElement>(null);
  const [measured, setMeasured] = React.useState<Record<string, { width: number; height: number }>>({});
  const [snap, setSnap] = React.useState(true);
  const [selectedEdges, setSelectedEdges] = React.useState<string[]>([]);
  const clipboard = React.useRef<{ nodes: WorkflowNode[]; edges: WorkflowEdge[]; pastes: number } | null>(null);
  const selectedRef = React.useRef(selected);
  React.useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);

  const selectedSet = React.useMemo(() => new Set(selected), [selected]);
  const bodies = React.useMemo(() => bodyOf(doc), [doc]);
  const inputNames = React.useMemo(() => doc.inputs.map((i) => i.name), [doc.inputs]);

  const nodes = React.useMemo<StudioFlowNode[]>(
    () =>
      doc.nodes.map((n) => {
        const nodeRun = run?.nodes[n.id];
        const duration = durationOf(nodeRun);
        const details = [
          duration !== null ? formatDuration(duration) : null,
          nodeRun?.costUsd ? formatUsd(nodeRun.costUsd, locale) : null,
          nodeRun && nodeRun.iterations > 1 ? `×${nodeRun.iterations}` : null,
        ]
          .filter(Boolean)
          .join(" · ");
        return {
          id: n.id,
          type: "studio" as const,
          position: n.position ?? { x: 0, y: 0 },
          data: {
            node: n,
            summary: nodeSummary(n.type, n.config, inputNames),
            issues: issuesByNode.get(n.id) ?? [],
            run: nodeRun,
            details,
            isBody: bodies.has(n.id),
            readOnly,
          },
          selected: selectedSet.has(n.id),
          measured: measured[n.id],
          draggable: !readOnly,
          deletable: !readOnly && n.type !== "input",
          connectable: !readOnly,
        };
      }),
    [doc.nodes, run, locale, inputNames, issuesByNode, bodies, readOnly, selectedSet, measured],
  );

  const edges = React.useMemo<Edge[]>(() => {
    const types = new Map(doc.nodes.map((n) => [n.id, n.type]));
    return doc.edges.map((e) => {
      const id = edgeId(e);
      const loop = isLoopEdge(doc, e);
      const fromCondition = types.get(e.source) === "condition";
      const sourceRun = run?.nodes[e.source]?.status;
      return {
        id,
        source: e.source,
        target: e.target,
        sourceHandle: fromCondition ? (e.condition ?? "true") : loop === "body" ? "body" : null,
        label: fromCondition
          ? e.condition === "false"
            ? t("canvas.branchFalse")
            : e.condition === "true"
              ? t("canvas.branchTrue")
              : t("canvas.branchMissing")
          : loop === "body"
            ? t("canvas.loopBody")
            : loop === "back"
              ? t("canvas.loopBack")
              : undefined,
        animated: sourceRun === "running",
        selected: selectedEdges.includes(id),
        deletable: !readOnly,
        style: {
          ...(loop ? { strokeDasharray: "4 4" } : {}),
          ...(issueEdges.has(id) ? { stroke: "var(--danger)", strokeWidth: 2 } : {}),
          ...(sourceRun === "success" ? { stroke: "var(--success)" } : {}),
        },
        labelStyle: { fontSize: 11, fill: "var(--fg-muted)" },
        labelBgStyle: { fill: "var(--surface)" },
      };
    });
  }, [doc, run, selectedEdges, readOnly, issueEdges, t]);

  // ------------------------------------------------------------------------------------------ changes

  const onNodesChange = React.useCallback(
    (changes: NodeChange<StudioFlowNode>[]) => {
      const dims: Record<string, { width: number; height: number }> = {};
      const positions = new Map<string, XYPosition>();
      const removed = new Set<string>();
      let selection: Set<string> | null = null;
      for (const c of changes) {
        if (c.type === "dimensions" && c.dimensions) dims[c.id] = c.dimensions;
        else if (c.type === "position" && c.position) positions.set(c.id, c.position);
        else if (c.type === "select") {
          selection ??= new Set(selectedRef.current);
          if (c.selected) selection.add(c.id);
          else selection.delete(c.id);
        } else if (c.type === "remove") removed.add(c.id);
      }
      if (Object.keys(dims).length) setMeasured((m) => ({ ...m, ...dims }));
      if (positions.size && !readOnly) {
        history.set(
          (d) => ({ ...d, nodes: d.nodes.map((n) => (positions.has(n.id) ? { ...n, position: positions.get(n.id) } : n)) }),
          { record: false },
        );
      }
      if (selection) onSelect([...selection]);
      if (removed.size && !readOnly) {
        const ids = new Set([...removed].filter((id) => doc.nodes.find((n) => n.id === id)?.type !== "input"));
        if (ids.size) {
          history.set((d) => removeNodes(d, ids));
          onSelect(selectedRef.current.filter((id) => !ids.has(id)));
        }
      }
    },
    [history, onSelect, readOnly, doc.nodes],
  );

  const onEdgesChange = React.useCallback(
    (changes: EdgeChange[]) => {
      const removed = new Set<string>();
      setSelectedEdges((current) => {
        let next = current;
        for (const c of changes) {
          if (c.type === "select") next = c.selected ? [...next.filter((x) => x !== c.id), c.id] : next.filter((x) => x !== c.id);
        }
        return next;
      });
      for (const c of changes) if (c.type === "remove") removed.add(c.id);
      if (removed.size && !readOnly) {
        history.set((d) => {
          const loopsToClear = new Set(
            d.edges.filter((e) => removed.has(edgeId(e)) && isLoopEdge(d, e) === "body").map((e) => e.source),
          );
          return {
            ...d,
            edges: d.edges.filter((e) => !removed.has(edgeId(e))),
            nodes: d.nodes.map((n) => (loopsToClear.has(n.id) ? { ...n, config: { ...n.config, body: "" } } : n)),
          };
        });
      }
    },
    [history, readOnly],
  );

  const connectionProblem = React.useCallback(
    (c: Connection | Edge): string | null => {
      if (!c.source || !c.target || c.source === c.target) return "canvas.connectSelf";
      const target = doc.nodes.find((n) => n.id === c.target);
      if (target?.type === "input") return "canvas.connectInput";
      if (c.sourceHandle === "body") return null;
      if (createsCycle(doc, { source: c.source, target: c.target })) return "canvas.cycleRejected";
      return null;
    },
    [doc],
  );

  const onConnect = React.useCallback(
    (c: Connection) => {
      if (readOnly) return;
      const problem = connectionProblem(c);
      if (problem) {
        toast.error(t(problem));
        return;
      }
      const source = doc.nodes.find((n) => n.id === c.source);
      if (!source) return;
      if (source.type === "loop" && c.sourceHandle === "body") {
        history.set((d) => {
          const previous = String(source.config.body ?? "");
          const edgesKept = d.edges.filter((e) => !(e.source === source.id && e.target === previous));
          return {
            ...d,
            nodes: d.nodes.map((n) => (n.id === source.id ? { ...n, config: { ...n.config, body: c.target } } : n)),
            edges: [...edgesKept, { source: source.id, target: c.target }],
          };
        });
        return;
      }
      const condition =
        source.type === "condition" ? (c.sourceHandle === "false" || c.sourceHandle === "true" ? c.sourceHandle : nextBranch(doc, source.id)) : null;
      history.set((d) => addEdge(d, { source: c.source, target: c.target, condition }));
    },
    [connectionProblem, doc, history, readOnly, t],
  );

  // --------------------------------------------------------------------------------------- add nodes

  const createNode = React.useCallback(
    (payload: DragPayload, position: XYPosition) => {
      if (readOnly) return;
      if (payload.type === "input" && doc.nodes.some((n) => n.type === "input")) {
        toast.error(t("canvas.inputUnique"));
        return;
      }
      const meta = palette.node_types.find((nt) => nt.type === payload.type);
      const config: Record<string, unknown> = structuredClone(meta?.defaults ?? {});
      if (payload.type === "llm") {
        config.model_tier = ["fast", "standard", "powerful"].includes(palette.default_tier) ? palette.default_tier : "standard";
      }
      if (payload.type === "custom" && payload.fn) config.function = payload.fn;
      const label = payload.fn ?? t(`nodeTypes.${payload.type}.label`);
      const id = uniqueId(doc, payload.fn ?? t(`nodeTypes.${payload.type}.idBase`));
      const snapped = snap ? { x: Math.round(position.x / GRID[0]) * GRID[0], y: Math.round(position.y / GRID[1]) * GRID[1] } : position;
      const node: WorkflowNode = { id, type: payload.type as NodeType, label, config, position: snapped };
      history.set((d) => ({ ...d, nodes: [...d.nodes, node] }));
      onSelect([id]);
    },
    [doc, history, onSelect, palette, readOnly, snap, t],
  );

  const addAtCenter = React.useCallback(
    (payload: DragPayload) => {
      const rect = wrapper.current?.getBoundingClientRect();
      const center = rect
        ? rf.screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 })
        : { x: 0, y: 0 };
      const jitter = (doc.nodes.length % 5) * 24;
      createNode(payload, { x: center.x - DEFAULT_SIZE.width / 2 + jitter, y: center.y - DEFAULT_SIZE.height / 2 + jitter });
    },
    [createNode, doc.nodes.length, rf],
  );

  const onDrop = React.useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData(DRAG_MIME);
      if (!raw) return;
      try {
        const payload = JSON.parse(raw) as DragPayload;
        const position = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
        createNode(payload, { x: position.x - DEFAULT_SIZE.width / 2, y: position.y - 20 });
      } catch {
        toast.error(t("canvas.dropFailed"));
      }
    },
    [createNode, rf, t],
  );

  // ----------------------------------------------------------------------------- copy, paste, align

  const copy = React.useCallback(() => {
    const ids = new Set(selectedRef.current);
    const picked = doc.nodes.filter((n) => ids.has(n.id) && n.type !== "input");
    if (!picked.length) return false;
    clipboard.current = {
      nodes: structuredClone(picked),
      edges: doc.edges.filter((e) => ids.has(e.source) && ids.has(e.target)),
      pastes: 0,
    };
    toast.success(t("canvas.copied", { count: picked.length }));
    return true;
  }, [doc, t]);

  const paste = React.useCallback(() => {
    const clip = clipboard.current;
    if (!clip || readOnly) return;
    clip.pastes += 1;
    const offset = { x: 40 * clip.pastes, y: 40 * clip.pastes };
    let created: string[] = [];
    history.set((d) => {
      const result = duplicate(d, clip.nodes, clip.edges, offset);
      created = result.ids;
      return result.config;
    });
    window.setTimeout(() => onSelect(created), 0);
  }, [history, onSelect, readOnly]);

  const removeSelected = React.useCallback(() => {
    if (readOnly) return;
    const ids = new Set(selectedRef.current.filter((id) => doc.nodes.find((n) => n.id === id)?.type !== "input"));
    if (selectedEdges.length) {
      const edgeIds = new Set(selectedEdges);
      history.set((d) => ({ ...removeNodes(d, ids), edges: removeNodes(d, ids).edges.filter((e) => !edgeIds.has(edgeId(e))) }));
      setSelectedEdges([]);
    } else if (ids.size) {
      history.set((d) => removeNodes(d, ids));
    }
    onSelect([]);
  }, [doc.nodes, history, onSelect, readOnly, selectedEdges]);

  const align = React.useCallback(
    (kind: "left" | "centerX" | "top" | "centerY" | "spreadX" | "spreadY") => {
      const ids = new Set(selectedRef.current);
      const picked = doc.nodes.filter((n) => ids.has(n.id) && n.position);
      if (picked.length < 2) return;
      const size = (id: string) => measured[id] ?? DEFAULT_SIZE;
      const xs = picked.map((n) => n.position?.x ?? 0);
      const ys = picked.map((n) => n.position?.y ?? 0);
      const positions = new Map<string, XYPosition>();
      if (kind === "left") picked.forEach((n) => positions.set(n.id, { x: Math.min(...xs), y: n.position?.y ?? 0 }));
      if (kind === "top") picked.forEach((n) => positions.set(n.id, { x: n.position?.x ?? 0, y: Math.min(...ys) }));
      if (kind === "centerX") {
        const center = picked.reduce((acc, n) => acc + (n.position?.x ?? 0) + size(n.id).width / 2, 0) / picked.length;
        picked.forEach((n) => positions.set(n.id, { x: center - size(n.id).width / 2, y: n.position?.y ?? 0 }));
      }
      if (kind === "centerY") {
        const center = picked.reduce((acc, n) => acc + (n.position?.y ?? 0) + size(n.id).height / 2, 0) / picked.length;
        picked.forEach((n) => positions.set(n.id, { x: n.position?.x ?? 0, y: center - size(n.id).height / 2 }));
      }
      if (kind === "spreadX" || kind === "spreadY") {
        const axis = kind === "spreadX" ? "x" : "y";
        const sorted = [...picked].sort((a, b) => (a.position?.[axis] ?? 0) - (b.position?.[axis] ?? 0));
        const first = sorted[0]?.position?.[axis] ?? 0;
        const last = sorted[sorted.length - 1]?.position?.[axis] ?? 0;
        const step = (last - first) / (sorted.length - 1);
        sorted.forEach((n, i) =>
          positions.set(n.id, axis === "x" ? { x: first + step * i, y: n.position?.y ?? 0 } : { x: n.position?.x ?? 0, y: first + step * i }),
        );
      }
      history.set((d) => ({ ...d, nodes: d.nodes.map((n) => (positions.has(n.id) ? { ...n, position: positions.get(n.id) } : n)) }));
    },
    [doc.nodes, history, measured],
  );

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isEditable(e.target)) return;
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) {
        e.preventDefault();
        if (!readOnly) history.undo();
      } else if ((key === "z" && e.shiftKey) || key === "y") {
        e.preventDefault();
        if (!readOnly) history.redo();
      } else if (key === "c") {
        if (copy()) e.preventDefault();
      } else if (key === "v") {
        if (clipboard.current) {
          e.preventDefault();
          paste();
        }
      } else if (key === "d") {
        e.preventDefault();
        if (copy()) paste();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [copy, history, paste, readOnly]);

  const multi = selected.length >= 2;
  const toolButton = (label: string, icon: React.ReactNode, onClick: () => void, disabled = false, pressed?: boolean) => (
    <Tooltip content={label}>
      <Button variant="ghost" size="icon-sm" aria-label={label} onClick={onClick} disabled={disabled} aria-pressed={pressed}>
        {icon}
      </Button>
    </Tooltip>
  );

  return (
    <div className="flex min-h-0 flex-1">
      <NodePalette
        nodeTypes={palette.node_types}
        functions={functions}
        hasInput={doc.nodes.some((n) => n.type === "input")}
        disabled={readOnly}
        onAdd={addAtCenter}
      />
      <div
        ref={wrapper}
        className="workflow-canvas relative min-h-0 flex-1"
        onDragOver={(e) => {
          if (readOnly) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
        }}
        onDrop={onDrop}
        aria-label={t("canvas.label")}
        style={
          {
            "--xy-background-color": "var(--bg)",
            "--xy-edge-stroke": "var(--border-strong)",
            "--xy-edge-stroke-selected": "var(--fg)",
            "--xy-connectionline-stroke": "var(--fg-muted)",
            "--xy-minimap-background-color": "var(--surface)",
            "--xy-minimap-mask-background-color": "color-mix(in srgb, var(--bg) 70%, transparent)",
            "--xy-controls-button-background-color": "var(--surface)",
            "--xy-controls-button-background-color-hover": "var(--subtle)",
            "--xy-controls-button-color": "var(--fg)",
            "--xy-controls-button-border-color": "var(--border)",
            "--xy-selection-background-color": "color-mix(in srgb, var(--accent) 8%, transparent)",
            "--xy-selection-border": "1px dashed var(--accent)",
          } as React.CSSProperties
        }
      >
        <ReactFlow<StudioFlowNode, Edge>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          isValidConnection={(c) => connectionProblem(c) === null}
          onNodeDragStart={() => history.begin()}
          onNodeDragStop={() => history.end()}
          onPaneClick={() => {
            onSelect([]);
            setSelectedEdges([]);
          }}
          onMoveEnd={(_, v: RFViewport) => props.onViewportChange({ x: v.x, y: v.y, zoom: v.zoom })}
          defaultViewport={props.viewport}
          snapToGrid={snap}
          snapGrid={GRID}
          deleteKeyCode={readOnly ? null : ["Delete", "Backspace"]}
          multiSelectionKeyCode={["Meta", "Control", "Shift"]}
          nodesDraggable={!readOnly}
          nodesConnectable={!readOnly}
          elementsSelectable
          colorMode={resolvedTheme === "dark" ? "dark" : "light"}
          minZoom={0.2}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={GRID[0]} size={1} color="var(--border-strong)" />
          <MiniMap pannable zoomable className="!rounded-md !border !border-border" ariaLabel={t("canvas.minimap")} />
          <Controls showInteractive={false} className="!rounded-md !border !border-border !shadow-none" />
          <Panel position="top-left" className="!m-2 flex items-center gap-0.5 rounded-md border border-border bg-surface p-0.5">
            {toolButton(t("canvas.undo"), <Undo2 />, history.undo, readOnly || !history.canUndo)}
            {toolButton(t("canvas.redo"), <Redo2 />, history.redo, readOnly || !history.canRedo)}
            <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />
            {toolButton(t("canvas.snap"), <Grid3x3 />, () => setSnap((s) => !s), false, snap)}
            {toolButton(t("canvas.alignLeft"), <AlignHorizontalJustifyStart />, () => align("left"), readOnly || !multi)}
            {toolButton(t("canvas.alignCenterX"), <AlignCenterVertical />, () => align("centerX"), readOnly || !multi)}
            {toolButton(t("canvas.alignTop"), <AlignVerticalJustifyStart />, () => align("top"), readOnly || !multi)}
            {toolButton(t("canvas.alignCenterY"), <AlignCenterHorizontal />, () => align("centerY"), readOnly || !multi)}
            {toolButton(t("canvas.spreadX"), <AlignHorizontalSpaceAround />, () => align("spreadX"), readOnly || selected.length < 3)}
            {toolButton(t("canvas.spreadY"), <AlignVerticalSpaceAround />, () => align("spreadY"), readOnly || selected.length < 3)}
            <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />
            {toolButton(t("canvas.copy"), <Copy />, () => void copy(), selected.length === 0)}
            {toolButton(t("canvas.paste"), <ClipboardPaste />, paste, readOnly || clipboard.current === null)}
            {toolButton(t("canvas.duplicate"), <CopyPlus />, () => {
              if (copy()) paste();
            }, readOnly || selected.length === 0)}
            {toolButton(t("canvas.delete"), <Trash2 />, removeSelected, readOnly || (selected.length === 0 && selectedEdges.length === 0))}
            <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />
            {toolButton(t("canvas.fitView"), <Maximize />, () => void rf.fitView({ padding: 0.2, duration: 200 }))}
          </Panel>
        </ReactFlow>
        {doc.nodes.length === 0 ? (
          <div className={cn("pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-fg-subtle")}>
            {t("canvas.empty")}
          </div>
        ) : null}
      </div>
    </div>
  );
}

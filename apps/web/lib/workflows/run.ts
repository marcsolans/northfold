/** Live execution of a workflow: engine SSE events → per-node status, input, output, duration and cost. */

import type { Span } from "@/lib/studio/types";

import type { NodeRun, NodeRunStatus, RunApproval } from "./types";

export type RunPhase = "idle" | "running" | "paused" | "success" | "error" | "cancelled";

export interface RunError {
  type?: string;
  message?: string;
}

export interface RunState {
  phase: RunPhase;
  workflow: string;
  runIds: string[];
  nodes: Record<string, NodeRun>;
  output?: unknown;
  error: RunError | null;
  approvals: RunApproval[];
  costUsd: number;
  durationMs: number;
  demo: boolean;
  startedAt: number | null;
}

export type StreamEvent = { type: string } & Record<string, unknown>;

export function initialRun(workflow: string): RunState {
  return {
    phase: "idle",
    workflow,
    runIds: [],
    nodes: {},
    error: null,
    approvals: [],
    costUsd: 0,
    durationMs: 0,
    demo: false,
    startedAt: null,
  };
}

/** `"<workflow>.<node>"` → node id; `"<workflow>.<loop>.<body>"` → body id (one iteration). */
export function nodeOfPath(path: unknown, workflow: string, known: Set<string>): string | null {
  if (typeof path !== "string") return null;
  const parts = path.split(".");
  if (parts[0] !== workflow) return null;
  if (parts.length === 2 && parts[1] && known.has(parts[1])) return parts[1];
  if (parts.length === 3 && parts[1] && parts[2] && known.has(parts[1]) && known.has(parts[2])) return parts[2];
  return null;
}

function statusOf(event: StreamEvent): { status: NodeRunStatus; reason: string | null } {
  const status = (event.status ?? {}) as { code?: string; reason?: string | null };
  const code = status.code ?? "success";
  if (code === "success") return { status: "success", reason: null };
  if (code === "cancelled" && (status.reason === "approval_required" || status.reason === "input_required")) {
    return { status: "paused", reason: status.reason };
  }
  return { status: "error", reason: status.reason ?? code };
}

function patch(state: RunState, id: string, update: Partial<NodeRun>): RunState {
  const previous: NodeRun = state.nodes[id] ?? { status: "idle", iterations: 0 };
  return { ...state, nodes: { ...state.nodes, [id]: { ...previous, ...update } } };
}

function asApprovals(value: unknown): RunApproval[] {
  return Array.isArray(value) ? (value.filter((a) => a && typeof a === "object") as RunApproval[]) : [];
}

export function reduceRun(state: RunState, event: StreamEvent, known: Set<string>): RunState {
  const now = Date.now();
  switch (event.type) {
    case "WORKFLOW_RUN":
      return { ...initialRun(state.workflow), phase: "running", startedAt: now };
    case "APPROVAL_RECORDED":
      return { ...state, phase: "running", approvals: [], error: null };
    case "RUN_STARTED": {
      const runId = typeof event.run_id === "string" ? event.run_id : null;
      return runId && !state.runIds.includes(runId) ? { ...state, runIds: [...state.runIds, runId] } : state;
    }
    case "START": {
      const id = nodeOfPath(event.path, state.workflow, known);
      if (!id) return state;
      const previous = state.nodes[id];
      return patch(state, id, {
        status: "running",
        startedAt: now,
        iterations: (previous?.iterations ?? 0) + (previous?.status === "running" ? 0 : 1),
        error: undefined,
      });
    }
    case "APPROVAL": {
      const id = nodeOfPath(event.path, state.workflow, known);
      return id ? patch(state, id, { status: "paused", input: event.input }) : state;
    }
    case "OUTPUT": {
      if (event.path === state.workflow && event.parent_call_id == null) {
        return { ...state, output: event.output };
      }
      const id = nodeOfPath(event.path, state.workflow, known);
      if (!id) return state;
      const { status } = statusOf(event);
      const metadata = (event.metadata ?? {}) as Record<string, unknown>;
      return patch(state, id, {
        status,
        input: event.input,
        output: event.output,
        error: event.error ?? undefined,
        t0: typeof event.t0 === "number" ? event.t0 : undefined,
        t1: typeof event.t1 === "number" ? event.t1 : undefined,
        replayed: Boolean(metadata.studio_replay) || undefined,
      });
    }
    case "RUN_ERROR": {
      const error = (event.error ?? {}) as RunError;
      return { ...state, error };
    }
    case "RUN_FINISHED": {
      const status = String(event.status ?? "error");
      const phase: RunPhase =
        status === "success" ? "success" : status === "paused" ? "paused" : status === "cancelled" ? "cancelled" : "error";
      const nodes = Object.fromEntries(
        Object.entries(state.nodes).map(([id, n]) => [id, n.status === "running" && phase !== "paused" ? { ...n, status: "error" as const } : n]),
      );
      if (phase === "success" || phase === "error" || phase === "cancelled") {
        for (const id of known) {
          if (!nodes[id]) nodes[id] = { status: "skipped", iterations: 0 };
        }
      }
      const error = (event.error ?? null) as RunError | null;
      return {
        ...state,
        phase,
        nodes,
        approvals: asApprovals(event.approvals),
        error: phase === "success" || phase === "paused" ? null : error ?? state.error,
        costUsd: state.costUsd + Number(event.cost_usd ?? 0),
        durationMs: state.durationMs + Number(event.duration_ms ?? 0),
        demo: Boolean(event.demo) || state.demo,
      };
    }
    default:
      return state;
  }
}

/** Cost per node from the run detail spans (every LLM span under the node's span). */
export function nodeCosts(spans: Span[], workflow: string, known: Set<string>): Record<string, number> {
  const children = new Map<string, Span[]>();
  for (const span of spans) {
    if (!span.parent_span_id) continue;
    children.set(span.parent_span_id, [...(children.get(span.parent_span_id) ?? []), span]);
  }
  const subtree = (span: Span): number => {
    let total = Number(span.cost_usd ?? 0);
    for (const child of children.get(span.id) ?? []) total += subtree(child);
    return total;
  };
  const costs: Record<string, number> = {};
  for (const span of spans) {
    const id = nodeOfPath(span.path, workflow, known);
    if (!id) continue;
    costs[id] = (costs[id] ?? 0) + subtree(span);
  }
  return costs;
}

export function durationOf(node: NodeRun | undefined): number | null {
  if (!node || node.t0 === undefined || node.t1 === undefined) return null;
  return Math.max(0, node.t1 - node.t0);
}

"use client";

/** Manual runs of a workflow streamed over SSE, approvals decided inline, and per-node costs afterwards. */

import * as React from "react";

import { http } from "@/lib/api";
import { errorMessage } from "@/lib/studio/hooks";
import { decisionStream, isAbortError, postStream } from "@/lib/studio/stream";
import type { DecisionBody, RunDetail } from "@/lib/studio/types";

import { workflowPath } from "./hooks";
import { initialRun, nodeCosts, reduceRun, type RunState, type StreamEvent } from "./run";

export function useWorkflowRun(projectId: string, workflow: string, known: Set<string>, fallbackError: string) {
  const [state, setState] = React.useState<RunState>(() => initialRun(workflow));
  const [busy, setBusy] = React.useState(false);
  const [deciding, setDeciding] = React.useState<string | null>(null);
  const abort = React.useRef<AbortController | null>(null);
  const knownRef = React.useRef(known);
  const costed = React.useRef<Set<string>>(new Set());
  React.useEffect(() => {
    knownRef.current = known;
  }, [known]);
  const mounted = React.useRef(true);
  React.useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      abort.current?.abort();
    };
  }, []);

  const onEvent = React.useCallback((event: StreamEvent) => {
    setState((s) => reduceRun(s, event, knownRef.current));
  }, []);

  const consume = React.useCallback(
    async (open: (signal: AbortSignal) => Promise<void>) => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      setBusy(true);
      try {
        await open(controller.signal);
      } catch (err) {
        if (!isAbortError(err)) {
          setState((s) => ({ ...s, phase: "error", error: { message: errorMessage(err, fallbackError) } }));
        }
      } finally {
        if (abort.current === controller) abort.current = null;
        setBusy(false);
      }
    },
    [fallbackError],
  );

  const start = React.useCallback(
    (input: Record<string, unknown>, event: Record<string, unknown> | null) => {
      costed.current = new Set();
      setState({ ...initialRun(workflow), phase: "running", startedAt: Date.now() });
      return consume((signal) =>
        postStream(`${workflowPath(projectId, workflow)}/run`, { input, event }, onEvent, signal),
      );
    },
    [consume, onEvent, projectId, workflow],
  );

  const decide = React.useCallback(
    async (approvalId: string, body: DecisionBody) => {
      setDeciding(approvalId);
      try {
        await consume((signal) => decisionStream(approvalId, body, onEvent, signal));
      } finally {
        setDeciding(null);
      }
    },
    [consume, onEvent],
  );

  const stop = React.useCallback(() => {
    abort.current?.abort();
    setState((s) => (s.phase === "running" ? { ...s, phase: "cancelled" } : s));
  }, []);

  const reset = React.useCallback(() => {
    abort.current?.abort();
    setState(initialRun(workflow));
  }, [workflow]);

  // Per-node cost from the persisted spans once a run (or a resumed run) has finished.
  React.useEffect(() => {
    if (state.phase === "running" || state.phase === "idle") return;
    const pending = state.runIds.filter((id) => !costed.current.has(id));
    if (!pending.length) return;
    pending.forEach((id) => costed.current.add(id));
    void Promise.all(pending.map((id) => http.get<RunDetail>(`/runs/${id}`).catch(() => null))).then((details) => {
      if (!mounted.current) return;
      const totals: Record<string, number> = {};
      for (const detail of details) {
        if (!detail) continue;
        for (const [id, cost] of Object.entries(nodeCosts(detail.spans, workflow, knownRef.current))) {
          totals[id] = (totals[id] ?? 0) + cost;
        }
      }
      setState((s) => ({
        ...s,
        nodes: Object.fromEntries(
          Object.entries(s.nodes).map(([id, n]) => [id, totals[id] !== undefined ? { ...n, costUsd: (n.costUsd ?? 0) + (totals[id] ?? 0) } : n]),
        ),
      }));
    });
  }, [state.phase, state.runIds, workflow]);

  return { state, busy, deciding, start, decide, stop, reset };
}

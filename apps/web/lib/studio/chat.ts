/**
 * Playground thread model: folds the run stream (engine events relayed by the API) into turns and parts.
 *
 * Event shapes: CONVERSATION, RUN_STARTED, START, DELTA (item: text_delta | text | tool_use | tool_use_delta |
 * thinking_delta | thinking | content_block_stop | custom), GUARDRAIL, APPROVAL, OUTPUT, RUN_ERROR,
 * RUN_FINISHED and, for streamed approval decisions, APPROVAL_RECORDED.
 */

import type { Role } from "@/lib/types";

import { sameId } from "./format";
import type { StreamEvent } from "./stream";
import type { Approval, Conversation, Decision, JsonSchema } from "./types";

export interface TextPart {
  type: "text";
  id: string;
  text: string;
}

export interface ThinkingPart {
  type: "thinking";
  id: string;
  text: string;
}

export type ToolState =
  | "streaming"
  | "running"
  | "done"
  | "error"
  | "awaiting_approval"
  | "approved"
  | "denied"
  | "blocked";

export interface ToolPart {
  type: "tool";
  /** Streamed content-block id (or the tool call id when the block was not streamed). */
  id: string;
  /** Tool call id from the model output, used by APPROVAL and tool OUTPUT events. */
  callId: string | null;
  name: string;
  inputText: string;
  input: unknown;
  output?: unknown;
  error?: unknown;
  state: ToolState;
}

export interface GuardrailPart {
  type: "guardrail";
  id: string;
  rail: string;
  stage: string;
  action: string;
  reason: string | null;
  shadow: boolean;
}

export type ApprovalState = "requested" | "pending" | "deciding" | "approved" | "denied" | "expired";

export interface ApprovalPart {
  type: "approval";
  id: string;
  /** Engine approval id (from the APPROVAL event). */
  engineId: string;
  /** Platform approval id (from RUN_FINISHED.approvals), required to decide. */
  approvalId: string | null;
  toolName: string;
  title: string;
  input: Record<string, unknown>;
  inputSchema: JsonSchema | null;
  assignedRole: Role | null;
  expiresAt: string | null;
  state: ApprovalState;
  decision: Decision | null;
  comment: string | null;
  error: string | null;
}

export interface ErrorPart {
  type: "error";
  id: string;
  message: string;
  code: string | null;
}

export type Part = TextPart | ThinkingPart | ToolPart | GuardrailPart | ApprovalPart | ErrorPart;

export interface RunFinished {
  runId: string;
  status: string;
  costUsd: string;
  credits: string;
  durationMs: number | null;
  demo: boolean;
  providers: string[];
  error: { type?: string; message?: string } | null;
}

export interface UserTurn {
  key: string;
  role: "user";
  text: string;
  at: string | null;
  attachments: string[];
}

export interface AssistantTurn {
  key: string;
  role: "assistant";
  runId: string | null;
  commit: string | null;
  rootPath: string | null;
  parts: Part[];
  finished: RunFinished | null;
  streaming: boolean;
  stopped: boolean;
  /** Approval whose decision started this (resumed) run. */
  resumeOf: string | null;
  /** The decision was recorded but other approvals of the run are still pending. */
  waitingOthers: boolean;
  /** Loaded from a saved conversation: text only, no live events. */
  history: boolean;
  model: string | null;
  sawTextDelta: boolean;
  startedAt: number | null;
}

export type Turn = UserTurn | AssistantTurn;

export interface ChatState {
  conversationId: string | null;
  turns: Turn[];
}

export type ChatAction =
  | { type: "reset" }
  | { type: "load"; conversation: Conversation; pending: Approval[] }
  | { type: "send"; userKey: string; turnKey: string; text: string; attachments: string[]; at: number }
  | { type: "resume_start"; turnKey: string; approvalId: string; at: number }
  | { type: "event"; turnKey: string; event: StreamEvent }
  | { type: "end"; turnKey: string; aborted?: boolean; error?: { message: string; code?: string } }
  | { type: "approval_deciding"; approvalId: string; decision: Decision }
  | { type: "approval_failed"; approvalId: string; message: string };

export const initialChat: ChatState = { conversationId: null, turns: [] };

let seq = 0;
export function nextKey(prefix = "k"): string {
  seq += 1;
  return `${prefix}-${Date.now().toString(36)}-${seq}`;
}

// ------------------------------------------------------------------------------------ helpers

function rec(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function s(value: unknown): string {
  return typeof value === "string" ? value : value === null || value === undefined ? "" : String(value);
}

function depth(path: string): number {
  return path ? path.split(".").length : 0;
}

/** Text of an engine Message (`{content: [{type: "text", text}]}`) or a plain string. */
export function textOf(output: unknown): string {
  if (typeof output === "string") return output;
  const o = rec(output);
  if (Array.isArray(o.content)) {
    return o.content
      .map((b) => rec(b))
      .filter((b) => b.type === "text")
      .map((b) => s(b.text))
      .join("");
  }
  if (typeof o.text === "string") return o.text;
  return "";
}

function parseJson(text: string): unknown {
  if (!text.trim()) return {};
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function emptyAssistant(key: string, at: number | null, extra: Partial<AssistantTurn> = {}): AssistantTurn {
  return {
    key,
    role: "assistant",
    runId: null,
    commit: null,
    rootPath: null,
    parts: [],
    finished: null,
    streaming: true,
    stopped: false,
    resumeOf: null,
    waitingOthers: false,
    history: false,
    model: null,
    sawTextDelta: false,
    startedAt: at,
    ...extra,
  };
}

function approvalFromRecord(a: Approval): ApprovalPart {
  return {
    type: "approval",
    id: `approval-${a.id}`,
    engineId: "",
    approvalId: a.id,
    toolName: a.tool_name,
    title: a.title,
    input: a.payload ?? {},
    inputSchema: a.input_schema,
    assignedRole: a.assigned_role,
    expiresAt: a.expires_at,
    state: a.status === "pending" ? "pending" : a.status,
    decision: null,
    comment: a.comment,
    error: null,
  };
}

function updateParts<T extends Part>(parts: Part[], match: (p: Part) => p is T, update: (p: T) => T): Part[] {
  let changed = false;
  const next = parts.map((p) => {
    if (!match(p)) return p;
    changed = true;
    return update(p);
  });
  return changed ? next : parts;
}

const isTool = (p: Part): p is ToolPart => p.type === "tool";
const isApproval = (p: Part): p is ApprovalPart => p.type === "approval";

function toolState(status: unknown, error: unknown): ToolState {
  const st = rec(status);
  const code = s(st.code);
  const reason = s(st.reason);
  if (code === "cancelled" && (reason === "approval_required" || reason === "input_required")) return "awaiting_approval";
  if (code === "cancelled" && reason === "approval_denied") return "denied";
  if (code === "blocked") return "blocked";
  if (code === "error" || error) return "error";
  return "done";
}

// ------------------------------------------------------------------------------------ event folding

function applyDelta(turn: AssistantTurn, event: StreamEvent): AssistantTurn {
  const path = s(event.path);
  const fromRoot = turn.rootPath
    ? path === turn.rootPath || path === `${turn.rootPath}.llm`
    : depth(path) <= 2;
  if (!fromRoot) return turn;
  const item = rec(event.item);
  const id = s(item.id) || "block";
  const parts = turn.parts;
  switch (item.type) {
    case "text_delta":
    case "text": {
      const piece = item.type === "text" ? s(item.text) : s(item.text_delta);
      const idx = parts.findIndex((p) => p.type === "text" && p.id === id);
      const next = [...parts];
      if (idx === -1) next.push({ type: "text", id, text: piece });
      else {
        const prev = parts[idx] as TextPart;
        next[idx] = { ...prev, text: item.type === "text" ? piece : prev.text + piece };
      }
      return { ...turn, parts: next, sawTextDelta: true };
    }
    case "thinking_delta":
    case "thinking": {
      const piece = item.type === "thinking" ? s(item.thinking) : s(item.thinking_delta);
      const idx = parts.findIndex((p) => p.type === "thinking" && p.id === id);
      const next = [...parts];
      if (idx === -1) next.push({ type: "thinking", id, text: piece });
      else {
        const prev = parts[idx] as ThinkingPart;
        next[idx] = { ...prev, text: item.type === "thinking" ? piece : prev.text + piece };
      }
      return { ...turn, parts: next };
    }
    case "tool_use": {
      if (parts.some((p) => p.type === "tool" && p.id === id)) return turn;
      const input = s(item.input);
      return {
        ...turn,
        parts: [
          ...parts,
          { type: "tool", id, callId: null, name: s(item.name), inputText: input, input: parseJson(input), state: "streaming" },
        ],
      };
    }
    case "tool_use_delta":
      return {
        ...turn,
        parts: updateParts(parts, (p): p is ToolPart => isTool(p) && p.id === id, (p) => {
          const inputText = p.inputText + s(item.input_delta);
          return { ...p, inputText, input: parseJson(inputText) };
        }),
      };
    case "content_block_stop":
      return {
        ...turn,
        parts: updateParts(parts, (p): p is ToolPart => isTool(p) && p.id === id && p.state === "streaming", (p) => ({
          ...p,
          input: parseJson(p.inputText),
          state: "running",
        })),
      };
    default:
      return turn;
  }
}

function applyLlmOutput(turn: AssistantTurn, output: unknown): AssistantTurn {
  // Non-streaming providers: recover text and tool calls from the LLM output message.
  const content = rec(output).content;
  if (!Array.isArray(content)) return turn;
  let parts = turn.parts;
  for (const raw of content) {
    const block = rec(raw);
    if (block.type === "tool_use") {
      const callId = s(block.id);
      const name = s(block.name);
      const input = block.input ?? {};
      if (!callId || parts.some((p) => p.type === "tool" && (p.callId === callId || p.id === callId))) continue;
      // The streamed block carries its own id: link it to the tool call id the model returned.
      const streamed = parts.findIndex((p) => p.type === "tool" && p.callId === null && p.name === name);
      if (streamed !== -1) {
        const prev = parts[streamed] as ToolPart;
        parts = parts.map((p, i) =>
          i === streamed ? { ...prev, callId, input, inputText: JSON.stringify(input), state: prev.state === "streaming" ? "running" : prev.state } : p,
        );
      } else {
        parts = [...parts, { type: "tool", id: callId, callId, name, inputText: JSON.stringify(input), input, state: "running" }];
      }
    } else if (block.type === "text" && !turn.sawTextDelta) {
      const text = s(block.text);
      if (text) parts = [...parts, { type: "text", id: `llm-${parts.length}`, text }];
    }
  }
  return parts === turn.parts ? turn : { ...turn, parts };
}

function applyOutput(turn: AssistantTurn, event: StreamEvent): AssistantTurn {
  const path = s(event.path);
  if (event.parent_call_id === null || event.parent_call_id === undefined) {
    if (turn.parts.some((p) => p.type === "text")) return turn;
    const text = textOf(event.output);
    return text ? { ...turn, parts: [...turn.parts, { type: "text", id: "output", text }] } : turn;
  }
  const root = turn.rootPath ?? path.split(".").slice(0, -1).join(".");
  if (depth(path) !== depth(root) + 1 || !path.startsWith(`${root}.`)) return turn;
  const segment = path.slice(root.length + 1);
  if (segment === "llm") return applyLlmOutput(turn, event.output);
  const meta = rec(event.metadata);
  const toolCallId = s(meta.tool_call_id);
  let idx = toolCallId
    ? turn.parts.findIndex((p) => p.type === "tool" && (p.callId === toolCallId || p.id === toolCallId))
    : -1;
  if (idx === -1) {
    idx = turn.parts.findIndex(
      (p) => p.type === "tool" && p.name === segment && p.output === undefined && p.error === undefined,
    );
  }
  const state = toolState(event.status, event.error);
  const next = [...turn.parts];
  if (idx === -1) {
    next.push({
      type: "tool",
      id: toolCallId || s(event.call_id) || `tool-${next.length}`,
      callId: toolCallId || null,
      name: segment,
      inputText: JSON.stringify(event.input ?? {}),
      input: event.input ?? {},
      output: event.output ?? undefined,
      error: event.error ?? undefined,
      state,
    });
  } else {
    const prev = next[idx] as ToolPart;
    next[idx] = {
      ...prev,
      output: state === "awaiting_approval" ? prev.output : (event.output ?? undefined),
      error: event.error ?? undefined,
      state,
    };
  }
  return { ...turn, parts: next };
}

function applyApprovalEvent(turn: AssistantTurn, event: StreamEvent): AssistantTurn {
  const engineId = s(event.approval_id);
  if (turn.parts.some((p) => p.type === "approval" && p.engineId === engineId)) return turn;
  const toolCallId = s(event.tool_call_id);
  const parts = toolCallId
    ? updateParts(
        turn.parts,
        (p): p is ToolPart => isTool(p) && (p.callId === toolCallId || p.id === toolCallId),
        (p) => ({ ...p, state: "awaiting_approval" }),
      )
    : turn.parts;
  const approval: ApprovalPart = {
    type: "approval",
    id: `approval-${engineId}`,
    engineId,
    approvalId: null,
    toolName: s(event.runnable_name) || s(event.path).split(".").pop() || "",
    title: s(event.prompt),
    input: rec(event.input),
    inputSchema: event.input_schema && typeof event.input_schema === "object" ? (event.input_schema as JsonSchema) : null,
    assignedRole: null,
    expiresAt: null,
    state: "requested",
    decision: null,
    comment: null,
    error: null,
  };
  return { ...turn, parts: [...parts, approval] };
}

function applyFinished(turn: AssistantTurn, event: StreamEvent): AssistantTurn {
  const err = event.error && typeof event.error === "object" ? (event.error as RunFinished["error"]) : null;
  const finished: RunFinished = {
    runId: s(event.run_id) || turn.runId || "",
    status: s(event.status) || "error",
    costUsd: s(event.cost_usd) || "0",
    credits: s(event.credits) || "0",
    durationMs: typeof event.duration_ms === "number" ? event.duration_ms : null,
    demo: Boolean(event.demo),
    providers: Array.isArray(event.providers) ? event.providers.map(s) : [],
    error: err,
  };
  let parts = turn.parts;
  const rows = Array.isArray(event.approvals) ? event.approvals.map(rec) : [];
  for (const row of rows) {
    const engineId = s(row.engine_approval_id);
    const patch = {
      approvalId: s(row.id),
      assignedRole: (s(row.assigned_role) || "admin") as Role,
      expiresAt: row.expires_at ? s(row.expires_at) : null,
      title: s(row.title),
    };
    const exists = parts.some((p) => p.type === "approval" && p.engineId === engineId && engineId);
    if (exists) {
      parts = updateParts(parts, (p): p is ApprovalPart => isApproval(p) && p.engineId === engineId, (p) => ({
        ...p,
        ...patch,
        title: p.title || patch.title,
        state: p.state === "requested" ? "pending" : p.state,
      }));
    } else {
      parts = [
        ...parts,
        {
          type: "approval",
          id: `approval-${patch.approvalId}`,
          engineId,
          toolName: s(row.tool_name),
          input: rec(row.payload),
          inputSchema: null,
          state: "pending",
          decision: null,
          comment: null,
          error: null,
          ...patch,
        },
      ];
    }
  }
  if (finished.status !== "success" && finished.status !== "paused" && err?.message) {
    const already = parts.some((p) => p.type === "error" && p.message === err.message);
    if (!already) parts = [...parts, { type: "error", id: `err-${parts.length}`, message: err.message, code: err.type ?? null }];
  }
  return { ...turn, parts, finished, runId: finished.runId || turn.runId, streaming: false };
}

export function applyEvent(turn: AssistantTurn, event: StreamEvent): AssistantTurn {
  switch (event.type) {
    case "RUN_STARTED":
      return { ...turn, runId: s(event.run_id) || turn.runId, commit: s(event.commit) || null };
    case "START":
      if ((event.parent_call_id === null || event.parent_call_id === undefined) && !turn.rootPath) {
        return { ...turn, rootPath: s(event.path) || null };
      }
      return turn;
    case "DELTA":
      return applyDelta(turn, event);
    case "OUTPUT":
      return applyOutput(turn, event);
    case "APPROVAL":
      return applyApprovalEvent(turn, event);
    case "GUARDRAIL":
      return {
        ...turn,
        parts: [
          ...turn.parts,
          {
            type: "guardrail",
            id: `guard-${turn.parts.length}`,
            rail: s(event.rail),
            stage: s(event.stage),
            action: s(event.action),
            reason: event.reason ? s(event.reason) : null,
            shadow: Boolean(event.shadow),
          },
        ],
      };
    case "RUN_ERROR": {
      const err = rec(event.error);
      return {
        ...turn,
        parts: [
          ...turn.parts,
          { type: "error", id: `err-${turn.parts.length}`, message: s(err.message) || s(event.error), code: s(err.type) || null },
        ],
      };
    }
    case "RUN_FINISHED":
      return applyFinished(turn, event);
    default:
      return turn;
  }
}

// ------------------------------------------------------------------------------------ reducer

function mapAssistant(state: ChatState, key: string, fn: (t: AssistantTurn) => AssistantTurn): ChatState {
  let changed = false;
  const turns = state.turns.map((t) => {
    if (t.role !== "assistant" || t.key !== key) return t;
    const next = fn(t);
    if (next !== t) changed = true;
    return next;
  });
  return changed ? { ...state, turns } : state;
}

function mapApproval(state: ChatState, approvalId: string, fn: (p: ApprovalPart) => ApprovalPart): ChatState {
  return {
    ...state,
    turns: state.turns.map((t) =>
      t.role === "assistant"
        ? { ...t, parts: updateParts(t.parts, (p): p is ApprovalPart => isApproval(p) && sameId(p.approvalId, approvalId), fn) }
        : t,
    ),
  };
}

function recordDecision(state: ChatState, turnKey: string, event: StreamEvent): ChatState {
  const approval = rec(event.approval);
  const id = s(approval.id);
  const status = s(approval.status);
  const toolName = s(approval.tool_name);
  let next = mapApproval(state, id, (p) => ({
    ...p,
    state: status === "approved" || status === "denied" || status === "expired" ? status : p.state,
    comment: approval.comment ? s(approval.comment) : p.comment,
    error: null,
  }));
  // The gated tool call of the paused turn reflects the decision (its execution shows in the resumed run).
  if (status === "approved" || status === "denied" || status === "expired") {
    next = {
      ...next,
      turns: next.turns.map((t) =>
        t.role === "assistant" && t.parts.some((p) => p.type === "approval" && sameId(p.approvalId, id))
          ? {
              ...t,
              parts: updateParts(
                t.parts,
                (p): p is ToolPart => isTool(p) && p.state === "awaiting_approval" && (!toolName || p.name === toolName),
                (p) => ({ ...p, state: status === "approved" ? "approved" : "denied" }),
              ),
            }
          : t,
      ),
    };
  }
  if (event.waiting_for_other_approvals) {
    next = mapAssistant(next, turnKey, (t) => ({ ...t, waitingOthers: true }));
  }
  return next;
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "reset":
      return initialChat;
    case "load": {
      const turns: Turn[] = [];
      const c = action.conversation;
      c.messages.forEach((m, i) => {
        if (m.role === "user") {
          turns.push({
            key: `h-${c.id}-${i}`,
            role: "user",
            text: m.text,
            at: m.at ?? null,
            attachments: Array.isArray(m.attachments) ? m.attachments.filter((a) => typeof a === "string") : [],
          });
        } else {
          turns.push(
            emptyAssistant(`h-${c.id}-${i}`, null, {
              runId: m.run_id ?? null,
              parts: [{ type: "text", id: "history", text: m.text }],
              streaming: false,
              history: true,
              model: m.model ?? null,
            }),
          );
        }
      });
      const pending = action.pending.filter((a) => a.status === "pending");
      for (const a of pending) {
        const host = [...turns]
          .reverse()
          .find((t): t is AssistantTurn => t.role === "assistant" && sameId(t.runId, a.run_id));
        if (host) host.parts = [...host.parts, approvalFromRecord(a)];
        else {
          turns.push(
            emptyAssistant(`h-${c.id}-approval-${a.id}`, null, {
              runId: a.run_id,
              parts: [approvalFromRecord(a)],
              streaming: false,
              history: true,
            }),
          );
        }
      }
      return { conversationId: c.id, turns };
    }
    case "send":
      return {
        ...state,
        turns: [
          ...state.turns,
          {
            key: action.userKey,
            role: "user",
            text: action.text,
            at: new Date(action.at).toISOString(),
            attachments: action.attachments,
          },
          emptyAssistant(action.turnKey, action.at),
        ],
      };
    case "resume_start":
      return { ...state, turns: [...state.turns, emptyAssistant(action.turnKey, action.at, { resumeOf: action.approvalId })] };
    case "event": {
      const ev = action.event;
      if (ev.type === "CONVERSATION") return { ...state, conversationId: s(ev.conversation_id) || state.conversationId };
      if (ev.type === "APPROVAL_RECORDED") return recordDecision(state, action.turnKey, ev);
      return mapAssistant(state, action.turnKey, (t) => applyEvent(t, ev));
    }
    case "end": {
      const next = mapAssistant(state, action.turnKey, (t) => {
        let parts = t.parts;
        if (action.error) {
          parts = [...parts, { type: "error", id: `err-${parts.length}`, message: action.error.message, code: action.error.code ?? null }];
        }
        return { ...t, parts, streaming: false, stopped: Boolean(action.aborted) && !t.finished };
      });
      // A resume stream that only recorded the decision (others still pending) leaves no run to show.
      return {
        ...next,
        turns: next.turns.filter(
          (t) => !(t.role === "assistant" && t.key === action.turnKey && t.resumeOf && !t.runId && t.parts.length === 0 && !t.waitingOthers && !t.stopped),
        ),
      };
    }
    case "approval_deciding":
      return mapApproval(state, action.approvalId, (p) => ({ ...p, state: "deciding", decision: action.decision, error: null }));
    case "approval_failed":
      return mapApproval(state, action.approvalId, (p) => ({ ...p, state: "pending", error: action.message }));
    default:
      return state;
  }
}

export function isStreaming(state: ChatState): boolean {
  return state.turns.some((t) => t.role === "assistant" && t.streaming);
}

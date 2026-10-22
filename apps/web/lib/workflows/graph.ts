/**
 * Pure graph helpers for the workflow canvas: the same rules the API enforces (unique ids, one input, at least
 * one output, no cycles except loop bodies, bindings only to upstream nodes…) so errors show inline while editing.
 */

import {
  LOOP_BODY_TYPES,
  type NodeType,
  type Position,
  type ValidationIssue,
  type WorkflowConfig,
  type WorkflowEdge,
  type WorkflowNode,
} from "./types";

export const PLACEHOLDER = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_-]+)*)\s*\}\}/g;
const ANY_BRACES = /\{\{(.*?)\}\}/g;
const IDENT = /^[a-z][a-z0-9_]{0,62}$/;
export const RESERVED_IDS = new Set([
  "input", "event", "item", "index", "wf", "workflow", "nodes", "studio", "true", "false", "null", "none", "self",
  "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del", "elif", "else", "except",
  "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass",
  "raise", "return", "try", "while", "with", "yield",
]);
const KEY = /^[A-Za-z_][A-Za-z0-9_-]{0,63}$/;
const EXPRESSION_FUNCS = new Set(["len", "abs", "min", "max", "round", "int", "float", "str", "bool", "lower", "upper", "empty"]);
const EXPRESSION_WORDS = new Set(["and", "or", "not", "in", "is", "true", "false", "null", "none", "True", "False", "None"]);

export interface Issue extends ValidationIssue {
  params?: Record<string, string | number>;
}

export function isValidId(id: string): boolean {
  return IDENT.test(id) && !RESERVED_IDS.has(id);
}

// ------------------------------------------------------------------------------------------- templates

export function placeholders(template: unknown): string[] {
  const found: string[] = [];
  const walk = (value: unknown) => {
    if (typeof value === "string") {
      for (const match of value.matchAll(PLACEHOLDER)) {
        const path = match[1];
        if (path && !found.includes(path)) found.push(path);
      }
    } else if (Array.isArray(value)) {
      value.forEach(walk);
    } else if (value && typeof value === "object") {
      Object.values(value).forEach(walk);
    }
  };
  walk(template);
  return found;
}

function malformed(template: unknown): string[] {
  const bad: string[] = [];
  const walk = (value: unknown) => {
    if (typeof value === "string") {
      for (const match of value.matchAll(ANY_BRACES)) {
        const text = match[0];
        PLACEHOLDER.lastIndex = 0;
        const ok = new RegExp(`^${PLACEHOLDER.source}$`).test(text);
        if (!ok) bad.push(text);
      }
    } else if (Array.isArray(value)) {
      value.forEach(walk);
    } else if (value && typeof value === "object") {
      Object.values(value).forEach(walk);
    }
  };
  walk(template);
  return bad;
}

/** Rewrite `{{old…}}` bindings to `{{new…}}` in any JSON-like value. */
export function renameInTemplate<T>(value: T, oldId: string, newId: string): T {
  const pattern = new RegExp(`(\\{\\{\\s*)${oldId}(?=[.\\s}])`, "g");
  const walk = (v: unknown): unknown => {
    if (typeof v === "string") return v.replace(pattern, `$1${newId}`);
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x)]));
    return v;
  };
  return walk(value) as T;
}

// ------------------------------------------------------------------------------------------------ graph

export function bodyOf(config: WorkflowConfig): Map<string, string> {
  const ids = new Set(config.nodes.map((n) => n.id));
  const map = new Map<string, string>();
  for (const n of config.nodes) {
    if (n.type !== "loop") continue;
    const body = typeof n.config.body === "string" ? n.config.body : "";
    if (body && ids.has(body) && body !== n.id && !map.has(body)) map.set(body, n.id);
  }
  return map;
}

/** Edges that order execution (a loop's body edge and the optional back edge are not part of the DAG). */
export function executionEdges(config: WorkflowConfig): WorkflowEdge[] {
  const bodies = bodyOf(config);
  const ids = new Set(config.nodes.map((n) => n.id));
  return config.edges.filter(
    (e) => ids.has(e.source) && ids.has(e.target) && bodies.get(e.target) !== e.source && bodies.get(e.source) !== e.target,
  );
}

export function isLoopEdge(config: WorkflowConfig, edge: WorkflowEdge): "body" | "back" | null {
  const bodies = bodyOf(config);
  if (bodies.get(edge.target) === edge.source) return "body";
  if (bodies.get(edge.source) === edge.target) return "back";
  return null;
}

export function ancestors(config: WorkflowConfig, nodeId: string, edges = executionEdges(config)): Set<string> {
  const incoming = new Map<string, string[]>();
  for (const e of edges) incoming.set(e.target, [...(incoming.get(e.target) ?? []), e.source]);
  const seen = new Set<string>();
  const todo = [...(incoming.get(nodeId) ?? [])];
  while (todo.length) {
    const current = todo.pop() as string;
    if (seen.has(current)) continue;
    seen.add(current);
    todo.push(...(incoming.get(current) ?? []));
  }
  return seen;
}

export function findCycle(config: WorkflowConfig, edges = executionEdges(config)): string[] | null {
  const bodies = bodyOf(config);
  const outgoing = new Map<string, string[]>();
  for (const e of edges) outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e.target]);
  const state = new Map<string, number>();
  const stack: string[] = [];
  const visit = (id: string): string[] | null => {
    state.set(id, 1);
    stack.push(id);
    for (const next of outgoing.get(id) ?? []) {
      if (state.get(next) === 1) return stack.slice(stack.indexOf(next));
      if (!state.get(next)) {
        const found = visit(next);
        if (found) return found;
      }
    }
    stack.pop();
    state.set(id, 2);
    return null;
  };
  for (const n of config.nodes) {
    if (bodies.has(n.id) || state.get(n.id)) continue;
    const found = visit(n.id);
    if (found) return found;
  }
  return null;
}

/** Would adding `edge` create a cycle (loop body edges excluded)? */
export function createsCycle(config: WorkflowConfig, edge: WorkflowEdge): boolean {
  const next = { ...config, edges: [...config.edges, edge] };
  return findCycle(next) !== null;
}

// ------------------------------------------------------------------------------------------- validation

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function obj(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function templatesOf(node: WorkflowNode): [string, unknown][] {
  const c = node.config;
  switch (node.type) {
    case "agent":
    case "llm":
      return [["prompt", c.prompt]];
    case "tool":
    case "connector_action":
    case "sub_workflow":
    case "custom":
      return Object.entries(obj(c.args)).map(([k, v]) => [`args.${k}`, v]);
    case "knowledge_search":
      return [["query", c.query]];
    case "sql_query":
      return [["params", c.params]];
    case "http_request":
      return [["url", c.url], ["body", c.body], ["query", c.query]];
    case "condition":
      return [["expression", c.expression]];
    case "loop":
      return c.mode === "count" ? [] : [["items", c.items]];
    case "transform":
    case "output":
      return [["value", c.value]];
    case "approval":
      return [["prompt", c.prompt], ...Object.entries(obj(c.payload)).map(([k, v]) => [`payload.${k}`, v] as [string, unknown])];
    default:
      return [];
  }
}

/** Light syntax check of a condition (the API runs the full check). */
export function expressionProblem(expression: string): { code: string; params?: Record<string, string> } | null {
  const source = expression.replace(PLACEHOLDER, "__v").trim();
  if (!source) return { code: "expressionEmpty" };
  let depth = 0;
  for (const ch of source) {
    if (ch === "(" || ch === "[") depth += 1;
    if (ch === ")" || ch === "]") depth -= 1;
    if (depth < 0) return { code: "expressionSyntax" };
  }
  if (depth !== 0) return { code: "expressionSyntax" };
  const withoutStrings = source.replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, "0");
  if (/[;`{}=]/.test(withoutStrings.replace(/==|!=|<=|>=/g, ""))) return { code: "expressionSyntax" };
  for (const word of withoutStrings.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? []) {
    if (word === "__v" || EXPRESSION_FUNCS.has(word) || EXPRESSION_WORDS.has(word)) continue;
    return { code: "expressionName", params: { name: word } };
  }
  return null;
}

export interface ValidationContext {
  agents?: string[] | null;
  workflows?: string[] | null;
  functions?: string[] | null;
  toolParams?: Record<string, string[]>;
  maxWait?: number;
}

export function validateGraph(config: WorkflowConfig, ctx: ValidationContext = {}): Issue[] {
  const issues: Issue[] = [];
  const push = (code: string, extra: Partial<Issue> = {}) => issues.push({ code, message: "", ...extra });
  const seen = new Set<string>();
  for (const n of config.nodes) {
    if (!isValidId(n.id)) push("invalidId", { node_id: n.id, params: { id: n.id } });
    if (seen.has(n.id)) push("duplicateId", { node_id: n.id, params: { id: n.id } });
    seen.add(n.id);
  }
  const names = config.inputs.map((i) => i.name);
  config.inputs.forEach((i) => {
    if (!isValidId(i.name)) push("invalidInput", { params: { name: i.name } });
  });
  if (new Set(names).size !== names.length) push("duplicateInput");
  const inputs = config.nodes.filter((n) => n.type === "input");
  if (inputs.length !== 1) push("inputCount", { node_id: inputs[1]?.id });
  if (!config.nodes.some((n) => n.type === "output")) push("noOutput");

  const byId = new Map(config.nodes.map((n) => [n.id, n]));
  const bodies = bodyOf(config);
  const pairs = new Set<string>();
  for (const e of config.edges) {
    const source = byId.get(e.source);
    const target = byId.get(e.target);
    if (!source || !target) continue;
    const key = `${e.source}->${e.target}`;
    if (pairs.has(key)) push("duplicateEdge", { edge: e, node_id: e.target });
    pairs.add(key);
    if (bodies.get(e.target) === e.source || bodies.get(e.source) === e.target) continue;
    if (target.type === "input") push("edgeIntoInput", { edge: e, node_id: target.id });
    if (source.type === "output") push("edgeFromOutput", { edge: e, node_id: source.id });
    if (source.type === "condition" && !e.condition) push("unlabeledBranch", { edge: e, node_id: source.id });
  }
  for (const n of config.nodes) {
    if (n.type !== "loop") continue;
    const body = str(n.config.body);
    if (!body || !byId.has(body) || body === n.id) {
      push("loopBody", { node_id: n.id, field: "body" });
      continue;
    }
    if (bodies.get(body) !== n.id) {
      push("loopBodyShared", { node_id: n.id, field: "body", params: { id: body } });
      continue;
    }
    const bodyNode = byId.get(body) as WorkflowNode;
    if (!LOOP_BODY_TYPES.includes(bodyNode.type)) push("loopBodyType", { node_id: body });
    if (!pairs.has(`${n.id}->${body}`)) push("loopBodyEdge", { node_id: n.id });
    for (const e of config.edges) {
      if ((e.target === body && e.source !== n.id) || (e.source === body && e.target !== n.id)) {
        push("loopBodyConnections", { node_id: body, edge: e });
      }
    }
    if (n.config.mode !== "count" && !str(n.config.items).trim()) push("loopItems", { node_id: n.id, field: "items" });
  }
  if (issues.length) return issues;

  const edges = executionEdges(config);
  const cycle = findCycle(config, edges);
  if (cycle) {
    const path = [...cycle, cycle[0]].join(" → ");
    cycle.forEach((id) => push("cycle", { node_id: id, params: { path } }));
    return issues;
  }
  const incoming = new Map<string, number>();
  edges.forEach((e) => incoming.set(e.target, (incoming.get(e.target) ?? 0) + 1));
  for (const n of config.nodes) {
    if (n.type !== "input" && !bodies.has(n.id) && !incoming.get(n.id)) push("disconnected", { node_id: n.id });
  }

  const inputNames = new Set(names);
  for (const n of config.nodes) {
    const loopId = bodies.get(n.id) ?? null;
    const upstream = loopId ? new Set([...ancestors(config, loopId, edges), loopId]) : ancestors(config, n.id, edges);
    for (const [field, template] of templatesOf(n)) {
      for (const bad of malformed(template)) push("bindingSyntax", { node_id: n.id, field, params: { binding: bad } });
      for (const path of placeholders(template)) {
        const [root = "", ...rest] = path.split(".");
        const binding = `{{${path}}}`;
        if (root === "event") continue;
        if (root === "input") {
          if (rest[0] && !inputNames.has(rest[0])) push("bindingInput", { node_id: n.id, field, params: { binding, name: rest[0] } });
          continue;
        }
        if (!byId.has(root)) push("bindingUnknown", { node_id: n.id, field, params: { binding, id: root } });
        else if (root === loopId) {
          if (rest[0] !== "item" && rest[0] !== "index") push("bindingLoop", { node_id: n.id, field, params: { binding, id: root } });
        } else if (bodies.has(root)) push("bindingBody", { node_id: n.id, field, params: { binding, id: root } });
        else if (!upstream.has(root)) push("bindingUpstream", { node_id: n.id, field, params: { binding, id: root } });
        else if (rest[0] !== "output") push("bindingOutput", { node_id: n.id, field, params: { binding, id: root } });
      }
    }
    nodeIssues(n, ctx, config.name).forEach((i) => issues.push(i));
  }
  return issues;
}

function nodeIssues(node: WorkflowNode, ctx: ValidationContext, selfName: string): Issue[] {
  const out: Issue[] = [];
  const c = node.config;
  const bad = (code: string, field?: string, params?: Record<string, string | number>) =>
    out.push({ code, message: "", node_id: node.id, field, params });
  const keys = (container: unknown, field: string) => {
    for (const key of Object.keys(obj(container))) if (!KEY.test(key)) bad("invalidKey", field, { key });
  };
  switch (node.type) {
    case "agent":
      if (!str(c.agent)) bad("missingAgent", "agent");
      else if (ctx.agents && !ctx.agents.includes(str(c.agent))) bad("unknownAgent", "agent", { name: str(c.agent) });
      if (!str(c.prompt).trim()) bad("missingPrompt", "prompt");
      break;
    case "llm":
      if (!str(c.prompt).trim()) bad("missingPrompt", "prompt");
      if (placeholders(c.system).length) bad("systemBindings", "system");
      if (c.model && !str(c.model).includes("/")) bad("invalidModel", "model");
      break;
    case "tool": {
      const params = ctx.toolParams?.[str(c.tool)];
      if (ctx.toolParams && !params) bad("unknownTool", "tool", { name: str(c.tool) });
      const options = obj(c.options);
      if (c.tool === "knowledge_search" && !(Array.isArray(options.kb_ids) && options.kb_ids.length)) bad("missingKb", "options.kb_ids");
      if (c.tool === "sql_query" && !str(options.kb_id)) bad("missingKb", "options.kb_id");
      break;
    }
    case "connector_action":
      if (!str(c.connection_id)) bad("missingConnection", "connection_id");
      if (!str(c.action)) bad("missingAction", "action");
      keys(c.args, "args");
      break;
    case "knowledge_search":
      if (!(Array.isArray(c.kb_ids) && c.kb_ids.length)) bad("missingKb", "kb_ids");
      if (!str(c.query).trim()) bad("missingQuery", "query");
      break;
    case "sql_query": {
      const sql = str(c.sql).trim().toLowerCase();
      if (!str(c.kb_id)) bad("missingKb", "kb_id");
      if (!sql) bad("missingSql", "sql");
      else if (!sql.startsWith("select") && !sql.startsWith("with")) bad("sqlReadonly", "sql");
      if (str(c.sql).includes("{{")) bad("sqlBindings", "sql");
      break;
    }
    case "http_request": {
      const url = str(c.url).trim();
      if (!url) bad("missingUrl", "url");
      else if (!new RegExp(`^${PLACEHOLDER.source}$`).test(url) && !/^https?:\/\//.test(url)) bad("invalidUrl", "url");
      break;
    }
    case "condition": {
      const problem = expressionProblem(str(c.expression));
      if (problem) bad(problem.code, "expression", problem.params);
      break;
    }
    case "wait": {
      const seconds = Number(c.seconds);
      if (!Number.isFinite(seconds) || seconds < 1 || seconds > (ctx.maxWait ?? 240)) bad("waitRange", "seconds", { max: ctx.maxWait ?? 240 });
      break;
    }
    case "approval":
      keys(c.payload, "payload");
      break;
    case "sub_workflow":
      if (!str(c.workflow)) bad("missingWorkflow", "workflow");
      else if (c.workflow === selfName) bad("recursiveWorkflow", "workflow");
      else if (ctx.workflows && !ctx.workflows.includes(str(c.workflow))) bad("unknownWorkflow", "workflow", { name: str(c.workflow) });
      keys(c.args, "args");
      break;
    case "custom":
      if (!str(c.function)) bad("missingFunction", "function");
      else if (ctx.functions && !ctx.functions.includes(str(c.function))) bad("unknownFunction", "function", { name: str(c.function) });
      keys(c.args, "args");
      break;
    default:
      break;
  }
  return out;
}

// ------------------------------------------------------------------------------------------ edit helpers

export function slugId(text: string): string {
  const base = text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
  return /^[a-z]/.test(base) ? base : `nodo_${base}`.replace(/_+$/, "");
}

export function uniqueId(config: WorkflowConfig, base: string, taken: Set<string> = new Set()): string {
  const used = new Set([...config.nodes.map((n) => n.id), ...taken]);
  let root = slugId(base) || "nodo";
  if (RESERVED_IDS.has(root)) root = `${root}_1`;
  if (!used.has(root)) return root;
  for (let i = 2; ; i += 1) {
    const candidate = `${root}_${i}`.slice(0, 63);
    if (!used.has(candidate)) return candidate;
  }
}

export function renameNode(config: WorkflowConfig, oldId: string, newId: string): WorkflowConfig {
  return {
    ...config,
    nodes: config.nodes.map((n) => {
      const renamed = n.id === oldId ? { ...n, id: newId } : n;
      const cfg = renameInTemplate(renamed.config, oldId, newId);
      if (renamed.type === "loop" && cfg.body === oldId) cfg.body = newId;
      return { ...renamed, config: cfg };
    }),
    edges: config.edges.map((e) => ({
      ...e,
      source: e.source === oldId ? newId : e.source,
      target: e.target === oldId ? newId : e.target,
    })),
  };
}

export function removeNodes(config: WorkflowConfig, ids: Set<string>): WorkflowConfig {
  return {
    ...config,
    nodes: config.nodes
      .filter((n) => !ids.has(n.id))
      .map((n) => (n.type === "loop" && ids.has(str(n.config.body)) ? { ...n, config: { ...n.config, body: "" } } : n)),
    edges: config.edges.filter((e) => !ids.has(e.source) && !ids.has(e.target)),
  };
}

export function addEdge(config: WorkflowConfig, edge: WorkflowEdge): WorkflowConfig {
  if (config.edges.some((e) => e.source === edge.source && e.target === edge.target)) return config;
  return { ...config, edges: [...config.edges, edge] };
}

export function nextBranch(config: WorkflowConfig, source: string): "true" | "false" {
  const taken = new Set(config.edges.filter((e) => e.source === source).map((e) => e.condition));
  return taken.has("true") && !taken.has("false") ? "false" : "true";
}

/** Copy of nodes (with new ids, bindings rewritten) and the edges between them, offset on the canvas. */
export function duplicate(
  config: WorkflowConfig,
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  offset: Position = { x: 40, y: 40 },
): { config: WorkflowConfig; ids: string[] } {
  const mapping = new Map<string, string>();
  const taken = new Set<string>();
  for (const n of nodes) {
    if (n.type === "input") continue;
    const id = uniqueId(config, n.id, taken);
    taken.add(id);
    mapping.set(n.id, id);
  }
  let copies: WorkflowNode[] = nodes
    .filter((n) => mapping.has(n.id))
    .map((n) => ({
      ...n,
      id: mapping.get(n.id) as string,
      position: { x: (n.position?.x ?? 0) + offset.x, y: (n.position?.y ?? 0) + offset.y },
    }));
  for (const [from, to] of mapping) {
    copies = copies.map((n) => {
      const cfg = renameInTemplate(n.config, from, to);
      if (n.type === "loop" && cfg.body === from) cfg.body = to;
      return { ...n, config: cfg };
    });
  }
  const copiedEdges = edges
    .filter((e) => mapping.has(e.source) && mapping.has(e.target))
    .map((e) => ({ ...e, source: mapping.get(e.source) as string, target: mapping.get(e.target) as string }));
  return {
    config: { ...config, nodes: [...config.nodes, ...copies], edges: [...config.edges, ...copiedEdges] },
    ids: copies.map((n) => n.id),
  };
}

export function defaultLabel(type: NodeType, label: string): string {
  return label || type;
}

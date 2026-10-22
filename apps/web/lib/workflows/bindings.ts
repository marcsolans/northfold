/** What a node can bind to (`{{input.x}}`, `{{event…}}`, `{{node.output…}}`, `{{loop.item}}`). */

import { ancestors, bodyOf, executionEdges } from "./graph";
import type { WorkflowConfig, WorkflowNode } from "./types";

export type BindingGroup = "inputs" | "event" | "nodes" | "loop";

export interface BindingOption {
  path: string;
  group: BindingGroup;
  nodeId?: string;
  /** Message key under `workflows.bindings.hints` describing the value. */
  hint?: string;
}

const EVENT_PATHS: [string, string][] = [
  ["event", "event"],
  ["event.type", "eventType"],
  ["event.body", "eventBody"],
  ["event.from", "eventFrom"],
  ["event.subject", "eventSubject"],
  ["event.text", "eventText"],
  ["event.filename", "eventFilename"],
  ["event.scheduled_at", "eventScheduled"],
];

const TOOL_OUTPUTS: Record<string, string[]> = {
  calculator: ["result"],
  current_datetime: ["iso", "date", "weekday"],
  read_url: ["text", "status", "url"],
  http_request: ["status", "body"],
  knowledge_search: ["results"],
  sql_query: ["rows", "columns", "row_count"],
};

function keysOf(value: unknown): string[] {
  return value && typeof value === "object" && !Array.isArray(value) ? Object.keys(value as Record<string, unknown>) : [];
}

export function outputFields(node: WorkflowNode): string[] {
  const c = node.config;
  switch (node.type) {
    case "http_request":
      return ["status", "body"];
    case "knowledge_search":
      return ["results"];
    case "sql_query":
      return ["rows", "columns", "row_count"];
    case "approval":
      return keysOf(c.payload);
    case "transform":
    case "output":
      return keysOf(c.value);
    case "wait":
      return ["waited_s"];
    case "tool":
      return TOOL_OUTPUTS[String(c.tool ?? "")] ?? [];
    default:
      return [];
  }
}

export function outputHint(node: WorkflowNode): string {
  switch (node.type) {
    case "agent":
    case "llm":
      return node.config.json_output ? "json" : "text";
    case "condition":
      return "boolean";
    case "loop":
      return "list";
    default:
      return "value";
  }
}

export function bindingOptions(config: WorkflowConfig, nodeId: string): BindingOption[] {
  const options: BindingOption[] = [];
  for (const input of config.inputs) options.push({ path: `input.${input.name}`, group: "inputs", hint: input.type });
  for (const [path, hint] of EVENT_PATHS) options.push({ path, group: "event", hint });
  const bodies = bodyOf(config);
  const loopId = bodies.get(nodeId);
  if (loopId) {
    options.push({ path: `${loopId}.item`, group: "loop", nodeId: loopId, hint: "loopItem" });
    options.push({ path: `${loopId}.index`, group: "loop", nodeId: loopId, hint: "loopIndex" });
  }
  const edges = executionEdges(config);
  const upstream = loopId ? ancestors(config, loopId, edges) : ancestors(config, nodeId, edges);
  for (const node of config.nodes) {
    if (!upstream.has(node.id) || node.type === "input" || bodies.has(node.id)) continue;
    options.push({ path: `${node.id}.output`, group: "nodes", nodeId: node.id, hint: outputHint(node) });
    for (const field of outputFields(node)) {
      options.push({ path: `${node.id}.output.${field}`, group: "nodes", nodeId: node.id });
    }
  }
  return options;
}

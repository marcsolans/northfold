import {
  ArrowRightToLine,
  Bot,
  Braces,
  CircleDot,
  Clock,
  Code2,
  Database,
  GitBranch,
  Globe,
  type LucideIcon,
  LogIn,
  Plug,
  Repeat,
  Search,
  Sparkles,
  UserCheck,
  Workflow,
  Wrench,
} from "lucide-react";

import type { NodeType, PaletteNodeType } from "@/lib/workflows/types";

export const NODE_ICONS: Record<NodeType, LucideIcon> = {
  input: LogIn,
  agent: Bot,
  llm: Sparkles,
  tool: Wrench,
  connector_action: Plug,
  knowledge_search: Search,
  sql_query: Database,
  http_request: Globe,
  condition: GitBranch,
  loop: Repeat,
  transform: Braces,
  approval: UserCheck,
  wait: Clock,
  sub_workflow: Workflow,
  output: ArrowRightToLine,
  custom: Code2,
};

export const FALLBACK_ICON = CircleDot;

export const CATEGORY_ORDER: PaletteNodeType["category"][] = ["flow", "ai", "actions", "data", "logic", "human", "custom"];

export const DRAG_MIME = "application/x-messer-node";

export interface DragPayload {
  type: NodeType;
  fn?: string;
}

function short(text: unknown, max = 48): string {
  const value = typeof text === "string" ? text : text === undefined || text === null ? "" : JSON.stringify(text);
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

/** One-line summary of a node's configuration (shown under its label on the canvas). */
export function nodeSummary(type: NodeType, config: Record<string, unknown>, inputs: string[]): string {
  switch (type) {
    case "input":
      return inputs.length ? inputs.join(", ") : "event";
    case "agent":
      return short(config.agent);
    case "llm":
      return short(config.model || config.model_tier);
    case "tool":
      return short(config.tool);
    case "connector_action":
      return short(config.action);
    case "knowledge_search":
      return short(config.query);
    case "sql_query":
      return short(config.sql);
    case "http_request":
      return `${String(config.method ?? "GET")} ${short(config.url, 40)}`;
    case "condition":
      return short(config.expression);
    case "loop":
      return config.mode === "count" ? `× ${String(config.count ?? 1)}` : short(config.items);
    case "transform":
    case "output":
      return short(config.value);
    case "approval":
      return short(config.prompt);
    case "wait":
      return `${String(config.seconds ?? 0)} s`;
    case "sub_workflow":
      return short(config.workflow);
    case "custom":
      return short(config.function);
    default:
      return "";
  }
}

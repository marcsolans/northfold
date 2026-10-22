/** Types mirroring the workflow builder API (`/api/v1/projects/{id}/workflows`) and triggers. */

import type { JsonSchema } from "@/lib/studio/types";
import type { Role } from "@/lib/types";

export const NODE_TYPES = [
  "input",
  "agent",
  "llm",
  "tool",
  "connector_action",
  "knowledge_search",
  "sql_query",
  "http_request",
  "condition",
  "loop",
  "transform",
  "approval",
  "wait",
  "sub_workflow",
  "output",
  "custom",
] as const;
export type NodeType = (typeof NODE_TYPES)[number];

export const LOOP_BODY_TYPES: readonly NodeType[] = [
  "agent",
  "llm",
  "tool",
  "connector_action",
  "knowledge_search",
  "sql_query",
  "http_request",
  "transform",
  "sub_workflow",
  "custom",
];

export type InputType = "string" | "number" | "boolean" | "object";
export type Branch = "true" | "false";

export interface Position {
  x: number;
  y: number;
}

export interface WorkflowInput {
  name: string;
  type: InputType;
  description: string;
  required: boolean;
}

export interface WorkflowNode {
  id: string;
  type: NodeType;
  label: string;
  config: Record<string, unknown>;
  position?: Position | null;
}

export interface WorkflowEdge {
  source: string;
  target: string;
  condition?: Branch | null;
}

export interface WorkflowConfig {
  name: string;
  description: string;
  inputs: WorkflowInput[];
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  custom_nodes: string[];
}

export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

export interface CustomFunctionParam {
  name: string;
  required: boolean;
  annotation: string | null;
}

export interface CustomFunction {
  name: string;
  description: string;
  params: CustomFunctionParam[];
  is_async: boolean;
  line: number;
}

export interface CustomNodes {
  code: string;
  functions: CustomFunction[];
  error: { message: string; line: number | null; column: number | null } | null;
}

export interface FlowGraph {
  nodes: { id: string; type: string; position?: Position; data?: Record<string, unknown> }[];
  edges: { id: string; source: string; target: string; kind?: string; when?: string }[];
}

export interface WorkflowDetail {
  id: string;
  name: string;
  kind: "workflow";
  description: string;
  path: string;
  source_mode: "config" | "code";
  current_version: number;
  updated_at: string;
  commit: string;
  code: string;
  config: WorkflowConfig | null;
  viewport: Viewport;
  positions: Record<string, Position>;
  custom_nodes: CustomNodes;
  flow: FlowGraph | null;
  flow_error: string | null;
}

export interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  source_mode: "config" | "code";
  current_version: number;
  updated_at: string;
  nodes: number;
  triggers: number;
  last_run: { id: string; status: string; started_at: string } | null;
}

export type StarterTemplate = "blank" | "approval" | "classify";

export interface PaletteNodeType {
  type: NodeType;
  category: "flow" | "ai" | "actions" | "data" | "logic" | "human" | "custom";
  config_schema: JsonSchema;
  defaults: Record<string, unknown>;
  loop_body: boolean;
}

export interface PaletteTool {
  key: string;
  label: string;
  side_effect: boolean;
  params: string[];
}

export interface PaletteConnection {
  id: string;
  name: string;
  connector_key: string;
  connector_name: string;
  status: string;
  demo: boolean;
}

export interface Palette {
  node_types: PaletteNodeType[];
  templates: StarterTemplate[];
  tools: PaletteTool[];
  agents: { name: string; description: string }[];
  workflows: { name: string; description: string }[];
  connections: PaletteConnection[];
  knowledge_bases: { id: string; name: string; description: string }[];
  model_tiers: { tier: "fast" | "standard" | "powerful"; model: string }[];
  default_tier: string;
  roles: Role[];
  limits: { max_wait_seconds: number; max_loop_items: number };
}

export interface ValidationIssue {
  code: string;
  message: string;
  node_id?: string;
  edge?: { source: string; target: string };
  field?: string;
}

// ---------------------------------------------------------------------------------------------- triggers

export const TRIGGER_KINDS = ["manual", "cron", "webhook", "email", "file", "connector_event"] as const;
export type TriggerKind = (typeof TRIGGER_KINDS)[number];

export interface TriggerHistoryEntry {
  at: string;
  event_id?: string;
  status: string;
  run_id?: string | null;
  error?: string;
}

export interface Trigger {
  id: string;
  kind: TriggerKind;
  name: string;
  config: Record<string, unknown> & { static_input?: Record<string, unknown> };
  environment: "development" | "production";
  enabled: boolean;
  workforce_id: string;
  project_id: string;
  last_fired_at: string | null;
  next_fire_at: string | null;
  webhook_url: string | null;
  inbound_address: string | null;
  state: { history?: TriggerHistoryEntry[]; last?: TriggerHistoryEntry; consecutive_failures?: number; disabled_reason?: string };
  secret?: string;
}

export interface ConnectorActionSpec {
  name: string;
  title: string;
  description: string;
  input_schema: JsonSchema | null;
  side_effect: boolean;
  requires_approval?: boolean;
}

// -------------------------------------------------------------------------------------------- live runs

export type NodeRunStatus = "idle" | "running" | "success" | "error" | "paused" | "skipped";

export interface NodeRun {
  status: NodeRunStatus;
  input?: unknown;
  output?: unknown;
  error?: unknown;
  startedAt?: number;
  t0?: number;
  t1?: number;
  iterations: number;
  replayed?: boolean;
  costUsd?: number;
}

export interface RunApproval {
  id: string;
  engine_approval_id: string;
  tool_name: string;
  title: string;
  payload: Record<string, unknown>;
  assigned_role: Role;
  expires_at: string | null;
}

/** Types mirroring the Guard API (`/api/v1/projects/{id}/guard`). */

export type ModelChoice = "small" | "large";
export type Confirmation = "none" | "majority" | "unanimous";
export type ToolActionKind = "allow" | "deny" | "require_approval";
export type LastMessage = "any" | "user_text" | "tool_result";
export type Operator = "<" | "<=" | ">" | ">=" | "==" | "!=" | "in" | "not_in" | "contains" | "matches" | "exists" | "missing";

export const OPERATORS: Operator[] = ["<", "<=", ">", ">=", "==", "!=", "in", "not_in", "contains", "matches", "exists", "missing"];
export const NUMERIC_OPERATORS: Operator[] = ["<", "<=", ">", ">="];
export const CONFIRMATIONS: Confirmation[] = ["none", "majority", "unanimous"];
export const TOOL_ACTIONS: ToolActionKind[] = ["allow", "deny", "require_approval"];
export const LAST_MESSAGES: LastMessage[] = ["any", "user_text", "tool_result"];

export interface ArgConstraint {
  arg: string;
  op: Operator;
  value: unknown;
}

export interface ToolAction {
  tool: string;
  action: ToolActionKind;
  constraints: ArgConstraint[];
  message: string | null;
}

export interface TurnMatch {
  last_message: LastMessage;
  tool_results: string[];
  text_patterns: string[];
  text_excludes: string[];
  min_chars: number | null;
  max_chars: number | null;
  first_turn: boolean | null;
}

export interface Policy {
  id: string;
  description: string;
  enabled: boolean;
  condition: string | null;
  match: TurnMatch;
  requires: string[];
  provides: string[];
  model: ModelChoice | null;
  tool_action: ToolAction | null;
  confirmation: Confirmation;
  response: string | null;
}

export interface Playbook {
  version: number;
  enabled: boolean;
  small_model: string;
  large_model: string;
  policies: Policy[];
  output_schema: Record<string, unknown> | null;
}

export interface Issue {
  level: "error" | "warning";
  path: string;
  code: string;
  message: string;
  params: Record<string, unknown>;
}

export interface GuardTool {
  name: string;
  kind: string;
  label: string;
  side_effect: boolean;
  gated: boolean;
  input_schema: Record<string, unknown> | null;
}

export interface GuardDetail {
  member: string;
  workforce_id: string;
  enabled: boolean;
  playbook: Partial<Playbook> | null;
  generated_by: "llm" | "rules" | "manual" | null;
  meta: {
    model?: string | null;
    cost_usd?: string;
    demo?: boolean;
    warnings?: string[];
    generated_at?: string;
    edited_at?: string;
  } & Record<string, unknown>;
  updated_at: string | null;
  updated_by: string | null;
  issues: Issue[];
  tools: GuardTool[];
  models: { id: string; label: string }[];
  defaults: { small_model: string; large_model: string };
  facts: string[];
  plan_allows: boolean;
}

export interface GuardMetrics {
  days: number;
  runs: number;
  turns: number;
  on_path_turns: number;
  on_path_share: number | null;
  blocked_actions: number;
  errors: number;
  invalid_outputs: number;
  routes: Record<string, number>;
  cost: {
    guarded_usd: string;
    baseline_usd: string;
    overhead_usd: string;
    per_run_guarded_usd: string | null;
    per_run_baseline_usd: string | null;
    savings_pct: number | null;
  };
  demo: boolean;
  daily: { day: string; turns: number; on_path: number; blocked: number }[];
  policies: { policy: string; turns: number; blocked: number }[];
}

export interface DecisionToolCall {
  id: string;
  tool: string;
  input: Record<string, unknown>;
  verdict: "allow" | "deny" | "approval" | "pass";
  policies: { policy: string; verdict: string; reason: string; missing?: string[] }[];
  explanation?: string;
}

export interface GuardDecision {
  span_id: string;
  run_id: string;
  at: string;
  channel: string | null;
  policy: string;
  action: string | null;
  status: string;
  route: string | null;
  model: string | null;
  requested_model: string | null;
  on_path: boolean;
  text: string;
  turn: string | null;
  tool_calls: DecisionToolCall[];
  blocked: { tool: string; policy: string; explanation: string | null }[];
  votes: { policy: string; matched: boolean; votes: (boolean | null)[]; skipped?: string; reasons?: string[] }[];
  facts: string[];
  latency_ms: number | null;
  overhead_cost_usd: string;
  priced_cost_usd: string | null;
  baseline_cost_usd: string | null;
  demo: boolean;
  errors: string[];
}

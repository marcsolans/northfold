/** Types mirroring the Studio API (projects, workforce, playground, runs, approvals). */

import type { Role } from "@/lib/types";

export type ModelTier = "fast" | "standard" | "powerful";
export const MODEL_TIERS: ModelTier[] = ["fast", "standard", "powerful"];

/** Decimal values are serialised by the API as strings. */
export type Money = string | number;

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string;
  default_model_tier: ModelTier;
  template_id: string | null;
  github_repo: string | null;
  created_at: string;
  updated_at: string;
  agents: number;
  workflows: number;
  runs_30d: number;
}

export interface Environment {
  id: string;
  name: "development" | "production" | string;
  status: string;
  url: string | null;
  custom_domain: string | null;
  deployed_version_id: string | null;
}

export type MemberKind = "agent" | "workflow";
export type SourceMode = "config" | "code";

export interface Member {
  id: string;
  name: string;
  kind: MemberKind;
  description: string;
  path: string;
  source_mode: SourceMode;
  current_version: number;
  guard_enabled: boolean;
  updated_at: string;
}

export interface MemberDetail extends Member {
  config: Partial<AgentConfig> & Record<string, unknown>;
  code: string;
  commit: string;
}

// ------------------------------------------------------------------------------------ agent configuration

export type ToolType = "builtin" | "connector" | "custom";

export interface ToolConfig {
  type: ToolType;
  key: string;
  name?: string | null;
  connection_id?: string | null;
  description?: string;
  input_schema?: JsonSchema | null;
  requires_approval: boolean;
  approver_role: Role;
  config: Record<string, unknown>;
}

export type GuardrailType = "pii" | "secrets" | "injection" | "topics" | "judge";
export const GUARDRAIL_TYPES: GuardrailType[] = ["pii", "secrets", "injection", "topics", "judge"];

export interface GuardrailConfig {
  type: GuardrailType;
  mode: "shadow" | "enforce";
  topics: string[];
  rubric: string;
}

export type CompactionStrategy = "none" | "tool_results" | "last_turns" | "summarize";
export const COMPACTION_STRATEGIES: CompactionStrategy[] = ["none", "tool_results", "last_turns", "summarize"];

export interface MemoryConfig {
  enabled: boolean;
  compaction: CompactionStrategy;
  keep_last_n: number;
}

export interface VoiceConfig {
  enabled: boolean;
  voice: string;
  language: string;
  greeting: string;
}

export interface PromptVariable {
  name: string;
  description: string;
  default: string;
}

/** Reference document next to the agent; managed only through the context-files endpoints. */
export interface ContextFile {
  name: string;
  mime: string;
  size: number;
}

export type McpApproval = "none" | "destructive" | "all";
export const MCP_APPROVALS: McpApproval[] = ["none", "destructive", "all"];

/** Remote MCP server (streamable HTTP). Header values may reference project secrets as `$SECRET_NAME`. */
export interface McpServerConfig {
  name: string;
  url: string;
  headers: Record<string, string>;
  approval: McpApproval;
}

/** Chat attachment stored by `POST /projects/{id}/uploads`. */
export interface Upload {
  id: string;
  name: string;
  mime: string;
  size: number;
}

export interface AgentConfig {
  name: string;
  description: string;
  model_tier: ModelTier | null;
  model: string | null;
  system_prompt: string;
  variables: PromptVariable[];
  temperature: number | null;
  max_tokens: number;
  max_iter: number;
  timeout: number | null;
  tools: ToolConfig[];
  knowledge_bases: string[];
  context_files: ContextFile[];
  mcp_servers: McpServerConfig[];
  guardrails: GuardrailConfig[];
  memory: MemoryConfig;
  voice: VoiceConfig;
}

export interface ToolCatalogItem {
  key: string;
  label: string;
  side_effect: boolean;
}

export interface ConnectionSummary {
  id: string;
  connector_key: string;
  connector_name: string;
  name: string;
  status: string;
  demo: boolean;
}

export interface ConnectorAction {
  name: string;
  title: string;
  description: string;
  input_schema: JsonSchema | null;
  side_effect: boolean;
  requires_approval?: boolean;
}

export interface KnowledgeBaseSummary {
  id: string;
  name: string;
  description: string;
  project_id: string | null;
}

// ------------------------------------------------------------------------------------ versions, files, evals

export interface Version {
  id: string;
  version: number;
  git_commit: string;
  message: string;
  author_id: string | null;
  created_at: string;
}

export interface FileList {
  ref: string;
  files: string[];
}

export interface FileContent {
  path: string;
  ref: string;
  content: string;
}

export interface EvalValidator {
  target: string;
  name: string;
  value: unknown;
  passed: boolean;
  evaluated: boolean;
  error: string | null;
  actual_value: unknown;
}

export interface EvalCaseResult {
  name?: string;
  path?: string;
  description?: string | null;
  tags?: string[];
  passed?: boolean;
  duration?: number;
  error?: unknown;
  params?: unknown;
  output?: unknown;
  validators?: EvalValidator[];
}

export interface EvalRun {
  id: string;
  status: "running" | "passed" | "failed" | "error" | string;
  trigger: string;
  passed: number;
  failed: number;
  results: EvalCaseResult[];
  created_at: string;
  finished_at: string | null;
}

// ------------------------------------------------------------------------------------ conversations

export interface ConversationSummary {
  id: string;
  title: string;
  message_count: number;
  last_run_id: string | null;
  updated_at: string;
}

export interface ConversationMessage {
  role: "user" | "assistant";
  text: string;
  run_id?: string | null;
  model?: string | null;
  at?: string;
  attachments?: string[];
}

export interface Conversation {
  id: string;
  workforce_name: string;
  title: string;
  messages: ConversationMessage[];
  last_run_id: string | null;
  created_at: string;
  updated_at: string;
}

// ------------------------------------------------------------------------------------ runs and traces

export type RunStatus =
  | "running"
  | "success"
  | "paused"
  | "error"
  | "timeout"
  | "blocked"
  | "cancelled"
  | "budget_exceeded";

export const RUN_STATUSES: RunStatus[] = [
  "running",
  "success",
  "paused",
  "error",
  "timeout",
  "blocked",
  "cancelled",
  "budget_exceeded",
];

export interface RunModel {
  model: string;
  providers?: string[];
}

export interface RunSummary {
  id: string;
  project_id: string;
  project_name: string | null;
  workforce_name: string;
  status: RunStatus | string;
  channel: string;
  environment: string;
  cost_usd: Money;
  credits: Money;
  duration_ms: number | null;
  models: (RunModel | string)[];
  user_id: string | null;
  external_user_id: string | null;
  conversation_id: string | null;
  parent_run_id: string | null;
  started_at: string;
  ended_at: string | null;
}

export interface RunPage {
  items: RunSummary[];
  next_cursor: string | null;
}

export type SpanKind = "agent" | "workflow" | "step" | "llm" | "tool" | "guardrail" | "guard" | string;

export interface Span {
  id: string;
  call_id: string;
  parent_span_id: string | null;
  kind: SpanKind;
  name: string;
  path: string;
  status: string;
  input: unknown;
  output: unknown;
  error: unknown;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cost_usd: Money;
  t0: number;
  t1: number | null;
  meta: Record<string, unknown>;
}

export interface RunApprovalBrief {
  id: string;
  tool_name: string;
  title: string;
  status: ApprovalStatus;
  assigned_role: Role;
  payload: Record<string, unknown>;
  resume_run_id: string | null;
}

export interface RunFeedback {
  id: string;
  value: "up" | "down";
  comment: string | null;
  user_id: string | null;
  created_at: string;
}

export interface RunDetail extends RunSummary {
  input: unknown;
  output: unknown;
  error: unknown;
  usage: Record<string, unknown>;
  git_commit: string | null;
  version_id: string | null;
  rerun_of: string | null;
  spans: Span[];
  approvals: RunApprovalBrief[];
  feedback: RunFeedback[];
  children: string[];
}

// ------------------------------------------------------------------------------------ approvals

export type ApprovalStatus = "pending" | "approved" | "denied" | "expired";
export type Decision = "approve" | "deny" | "approve_with_changes";

export interface Approval {
  id: string;
  project_id: string;
  project_name: string | null;
  run_id: string;
  workforce_name: string;
  tool_name: string;
  title: string;
  payload: Record<string, unknown>;
  input_schema: JsonSchema | null;
  context_summary: string;
  assigned_role: Role;
  status: ApprovalStatus;
  decided_by: string | null;
  decided_at: string | null;
  decision_via: string | null;
  comment: string | null;
  corrected_payload: Record<string, unknown> | null;
  expires_at: string | null;
  expiry_action: string;
  resume_run_id: string | null;
  environment: string;
  channel: string | null;
  created_at: string;
  can_decide: boolean;
}

export interface ApprovalPage {
  items: Approval[];
  pending: number;
}

export interface DecisionBody {
  decision: Decision;
  comment?: string;
  payload?: Record<string, unknown>;
}

export interface ApprovalLink {
  approval_id: string;
  decision: "approve" | "deny";
  title: string;
  workforce_name: string;
  tool_name: string;
  payload: Record<string, unknown>;
  project_name: string | null;
  status: ApprovalStatus;
  expires_at: string | null;
}

export interface ApprovalLinkResult {
  approval_id: string;
  status: ApprovalStatus;
  resumed: boolean;
}

export interface CreditsOverview {
  balance: Money;
  credits_month: number;
  used_this_month: Money;
  credit_usd: Money;
  test_mode: boolean;
}

// ------------------------------------------------------------------------------------ JSON Schema (subset)

export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  enum?: unknown[];
  items?: JsonSchema;
  default?: unknown;
  format?: string;
  [key: string]: unknown;
}

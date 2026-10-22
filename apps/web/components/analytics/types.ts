/** Types of the governance API (/api/v1/analytics, /metrics, /alarms, /model-policy). Decimals arrive as strings. */

export type Bucket = "hour" | "day" | "week";
export type GroupBy = "org" | "project" | "agent" | "channel" | "environment" | "user" | "model";
export type SortKey = "runs" | "cost_usd" | "errors" | "error_rate" | "p95_ms" | "users" | "credits" | "last_run_at";
export type EnvironmentName = "development" | "production";
export type MetricUnit = "count" | "percent" | "ms" | "usd" | "credits" | "tokens";

export interface Kpis {
  runs: number;
  success: number;
  errors: number;
  terminal: number;
  success_rate: number | null;
  error_rate: number | null;
  cost_usd: string;
  credits: string;
  users: number;
  p50_ms: number | null;
  p95_ms: number | null;
  avg_ms: number | null;
  last_run_at: string | null;
}

export interface FeedbackSummary {
  up: number;
  down: number;
  total: number;
  up_ratio: number | null;
}

export interface ModelUsage {
  model: string;
  label: string;
  runs: number;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
  errors: number;
  p50_ms: number | null;
  p95_ms: number | null;
}

export interface Overview {
  since: string;
  until: string;
  kpis: Kpis;
  previous: Kpis;
  feedback: FeedbackSummary;
  top_models: ModelUsage[];
}

export interface SeriesPoint {
  t: string;
  runs: number;
  success: number;
  errors: number;
  error_rate: number | null;
  cost_usd: string;
  credits: string;
  users: number;
  p50_ms: number | null;
  p95_ms: number | null;
}

export interface Timeseries {
  since: string;
  until: string;
  bucket: Bucket;
  tz: string;
  points: SeriesPoint[];
}

export interface BreakdownRow {
  key: string;
  label: string;
  project_id: string | null;
  project_name: string | null;
  runs: number;
  success: number | null;
  errors: number;
  terminal: number | null;
  success_rate: number | null;
  error_rate: number | null;
  cost_usd: string;
  credits: string | null;
  users: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  avg_ms: number | null;
  last_run_at: string | null;
  calls: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
}

export interface Breakdown {
  group_by: GroupBy;
  since: string;
  until: string;
  rows: BreakdownRow[];
}

export interface FeedbackComment {
  id: string;
  run_id: string;
  value: "up" | "down";
  comment: string;
  created_at: string;
  project_id: string | null;
  project_name: string | null;
  workforce_name: string;
  channel: string;
  user: string | null;
}

export interface FeedbackDetail extends FeedbackSummary {
  comments: FeedbackComment[];
}

export interface FilterOption {
  value: string;
  label: string;
}

export interface FilterOptions {
  projects: FilterOption[];
  environments: string[];
  channels: string[];
  agents: FilterOption[];
}

// ------------------------------------------------------------------------------------------ custom metrics

export type MetricSource = "spans" | "runs";
export type MetricAggregate = "count" | "sum" | "avg" | "min" | "max" | "p50" | "p95";
export type MetricField = "cost_usd" | "duration" | "tokens" | "input_tokens" | "output_tokens" | "credits";
export type SpanKind = "llm" | "tool" | "step" | "agent" | "workflow" | "guardrail" | "guard";

export interface MetricFilter {
  kind?: SpanKind | null;
  name?: string | null;
  status?: string | null;
  model?: string | null;
  path_glob?: string | null;
  output_contains?: string | null;
  error?: boolean | null;
}

export interface MetricDefinition {
  source: MetricSource;
  filter: MetricFilter;
  aggregate: MetricAggregate;
  field: MetricField | null;
}

export interface CustomMetric {
  id: string;
  name: string;
  description: string;
  definition: MetricDefinition;
  unit: MetricUnit;
  valid: boolean;
  alarm_count: number;
  created_at: string;
}

export interface MetricValues {
  since: string;
  until: string;
  bucket: Bucket;
  tz: string;
  unit: MetricUnit;
  total: number | null;
  points: { t: string; value: number | null }[];
}

// ------------------------------------------------------------------------------------------ alarms

export type Comparator = ">" | ">=" | "<" | "<=" | "==" | "!=";
export type DeliveryChannel = "email" | "slack";

export interface Alarm {
  id: string;
  name: string;
  project_id: string | null;
  project_name: string | null;
  metric: string;
  metric_name: string | null;
  unit: MetricUnit;
  comparator: Comparator;
  threshold: number;
  window_minutes: number;
  channels: DeliveryChannel[];
  environment: EnvironmentName | null;
  run_channel: string | null;
  workforce_name: string | null;
  slack_channel: string | null;
  enabled: boolean;
  state: "ok" | "firing";
  last_value: number | null;
  last_evaluated_at: string | null;
  last_fired_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlarmEvent {
  id: string;
  from_state: "ok" | "firing";
  to_state: "ok" | "firing";
  value: number | null;
  metric: string;
  comparator: Comparator;
  threshold: number;
  window_minutes: number;
  delivery: { in_app?: number; email?: number; slack?: string };
  created_at: string;
}

export interface AlarmTest {
  value: number | null;
  breached: boolean;
  unit: MetricUnit;
  state: "ok" | "firing";
  error: string | null;
  evaluated_at: string;
}

export interface AlarmCatalog {
  builtin: { key: string; unit: MetricUnit; name: string | null }[];
  custom: { key: string; unit: MetricUnit; name: string | null }[];
  slack_connected: boolean;
}

// ------------------------------------------------------------------------------------------ model policy

export interface PolicyModel {
  model: string;
  display_name: string;
  provider: string;
  tiers: string[];
  roles: string[];
  allowed: boolean;
  reason: "default" | "allowed" | "denied" | "not_allowed";
  pattern: string | null;
}

export interface PolicyIssue {
  field?: "allow" | "deny" | null;
  pattern?: string | null;
  code: string;
  message?: string | null;
  tier?: string | null;
  role?: string | null;
  model?: string | null;
}

export interface ModelPolicy {
  rules: { allow: string[]; deny: string[] };
  updated_at: string | null;
  models: PolicyModel[];
  allowed_count: number;
  total: number;
  warnings: PolicyIssue[];
  errors: PolicyIssue[];
}

// ------------------------------------------------------------------------------------------ eval comparison

export interface EvalVersion {
  key: string;
  version_id: string | null;
  number: number | null;
  entity_type: "workforce" | "project" | null;
  message: string | null;
  git_commit: string | null;
  created_at: string | null;
  eval_runs: number;
  passed: number;
  failed: number;
  errored_runs: number;
  pass_rate: number | null;
  last_eval_at: string;
  inferred: boolean;
}

export interface EvalComparison {
  workforce: string;
  kind: "agent" | "workflow";
  versions: EvalVersion[];
  cases: { name: string; description: string | null; results: Record<string, { passed: number; total: number; rate: number }> }[];
}

/** Types mirroring the interface spec (`interfaces/<slug>/interface.json`) and the interfaces API. */

import type { Role } from "@/lib/types";

export const COMPONENT_TYPES = [
  "data_table",
  "chart",
  "kpi",
  "form",
  "chat",
  "record_list",
  "calendar",
  "file_upload",
  "action_button",
  "approvals_inbox",
] as const;
export type ComponentType = (typeof COMPONENT_TYPES)[number];

export type BindingKind = "knowledge_sql" | "knowledge_search" | "agent" | "workflow" | "approvals" | "static";
export type Scalar = string | number | boolean | null;
export type SqlParam = Scalar | { input: string; default?: Scalar } | { context: string };

export const CONTEXT_KEYS = ["today", "now", "month_start", "month_end", "year_start", "user_id", "user_email"] as const;

export interface KnowledgeSqlBinding {
  kind: "knowledge_sql";
  kb_id: string;
  sql: string;
  params: SqlParam[];
  limit?: number;
}
export interface KnowledgeSearchBinding {
  kind: "knowledge_search";
  kb_ids: string[];
  query?: string;
  query_input?: string | null;
  mode?: "hybrid" | "vector" | "keyword";
  k?: number;
}
export interface AgentBinding {
  kind: "agent";
  workforce: string;
  prompt?: string | null;
}
export interface WorkflowBinding {
  kind: "workflow";
  workforce: string;
  input_mapping: Record<string, Scalar>;
}
export interface ApprovalsBinding {
  kind: "approvals";
  project?: string;
  status?: "pending" | "all";
}
export interface StaticBinding {
  kind: "static";
  data: Record<string, unknown>[] | Record<string, unknown>;
}
export type Binding =
  | KnowledgeSqlBinding
  | KnowledgeSearchBinding
  | AgentBinding
  | WorkflowBinding
  | ApprovalsBinding
  | StaticBinding;

/** What public pages receive instead of a binding: its kind and the inputs it reads. */
export interface ClientBinding {
  kind: BindingKind;
  query_input?: string | null;
  inputs?: string[];
}

export interface Grid {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Option {
  value: string;
  label: string;
}

export type ValueFormat = "text" | "number" | "currency" | "percent" | "date" | "datetime" | "boolean" | "badge";

export interface ColumnDef {
  key: string;
  label?: string | null;
  format?: ValueFormat;
  align?: "left" | "center" | "right" | null;
}

export interface FilterDef {
  name: string;
  label: string;
  type?: "text" | "select" | "date" | "number";
  options?: Option[];
  default?: Scalar;
}

export interface RowAction {
  label: string;
  binding: AgentBinding | WorkflowBinding | ClientBinding | null;
  confirm?: string | null;
}

export interface FormFieldDef {
  name: string;
  label: string;
  type?: "text" | "textarea" | "number" | "email" | "date" | "select" | "checkbox";
  required?: boolean;
  placeholder?: string | null;
  help?: string | null;
  options?: Option[];
  default?: Scalar;
  min?: number | null;
  max?: number | null;
  max_length?: number | null;
}

export interface ComponentDef {
  id: string;
  type: ComponentType;
  title?: string | null;
  description?: string | null;
  grid: Grid;
  props: Record<string, unknown>;
  binding?: Binding | ClientBinding | null;
}

export interface ScreenDef {
  id: string;
  title: string;
  layout?: "grid";
  components: ComponentDef[];
}

export interface ThemeDef {
  accent?: string;
  mode?: "system" | "light" | "dark";
  density?: "comfortable" | "compact";
  logo_url?: string | null;
}

export interface InterfaceDefinition {
  version?: number;
  name: string;
  slug: string;
  kind: "app" | "chat";
  description?: string;
  theme?: ThemeDef;
  auth?: { required?: boolean | null; roles?: Role[] };
  screens: ScreenDef[];
}

export interface Issue {
  path: string;
  code: string;
  message: string;
}

export interface InterfaceUrls {
  public: string | null;
  embed: string | null;
  widget: string | null;
}

export interface InterfaceSummary {
  id: string;
  project_id: string;
  name: string;
  slug: string;
  kind: "app" | "chat";
  public: boolean;
  auth_required: boolean;
  workforce_name: string | null;
  screens: number;
  components: number;
  valid: boolean;
  published: boolean;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  urls: InterfaceUrls;
}

export interface InterfaceDetail extends InterfaceSummary {
  definition: InterfaceDefinition;
  issues: Issue[];
  warnings: Issue[];
  commit: string | null;
  published_definition: InterfaceDefinition | null;
  production: { deployed: boolean; status: string | null; url: string | null };
}

export interface TemplateInfo {
  key: string;
  kind: "app" | "chat";
  name: string;
  name_en: string;
  description: string;
  description_en: string;
  requires: ("kb_id" | "table" | "agent")[];
}

export interface VersionInfo {
  sha: string;
  message: string;
  author: string;
  date: string;
}

export interface DataResult {
  source: string;
  columns: string[];
  column_types: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
}

export interface ActionResult {
  run_id: string;
  status: string;
  output: unknown;
  text: string;
  error: string | null;
  approvals_pending: number;
  demo: boolean;
}

export interface UploadResult {
  file: { id: string; filename: string; kb_id: string; mime: string; size: number; status: string };
  run: ActionResult | null;
}

export interface ConversationView {
  messages: { role: "user" | "assistant"; text: string; at: string | null }[];
  pending_approvals: number;
}

export interface PublicView {
  org: { name: string; slug: string };
  project: { name: string; slug: string };
  interface: InterfaceDefinition;
  viewer: { authenticated: boolean; role: Role | null; email: string | null; can_upload: boolean };
  published_at: string | null;
  end_user_token?: string;
}

export interface Deployment {
  id: string;
  environment: string;
  status: string;
  version: number | null;
  git_commit: string | null;
  logs: { at: string; level: string; message: string }[];
  forced: boolean;
  created_at: string;
  finished_at: string | null;
}

/** Sanitized run events streamed to chat components (see services/interfaces.end_user_stream). */
export type ChatEvent =
  | { type: "RUN_STARTED" }
  | { type: "TEXT"; text: string; segment: number }
  | { type: "ACTIVITY" }
  | { type: "APPROVAL_PENDING" }
  | { type: "DONE"; status: string; run_id: string; demo: boolean; approvals_pending: number; message?: string }
  | { type: "ERROR"; code: string; message: string };

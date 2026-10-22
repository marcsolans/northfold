export type AuthType = "oauth2" | "api_key" | "connection_string" | "none" | "mcp" | "agent";
export type Category = "files" | "communication" | "productivity" | "crm" | "database" | "developer";

export interface ConfigField {
  key: string;
  kind: "text" | "secret" | "url" | "textarea" | "boolean" | "select" | "number" | "json" | "list";
  required: boolean;
  secret: boolean;
  default: unknown;
  options: string[];
  placeholder: string | null;
}

export interface ConnectorEventSpec {
  name: string;
  event: string;
  title: string;
  title_en: string;
  description: string;
  delivery: "poll" | "push";
}

export interface ConnectorItem {
  key: string;
  name: string;
  category: Category;
  auth_type: AuthType;
  description: string;
  description_en: string;
  icon: string | null;
  capabilities: {
    actions: string[];
    sync: boolean;
    sync_resources: string[];
    events: string[];
    introspection: boolean;
    demo: boolean;
    agent: boolean;
  };
  events: ConnectorEventSpec[];
  config_fields: ConfigField[];
  docs_url: string | null;
  oauth: { provider: string; scopes: string[] } | null;
  availability: { mode: "live" | "oauth" | "demo"; missing_env: string[] };
}

export interface CatalogResponse {
  items: ConnectorItem[];
  categories: { key: Category; count: number }[];
}

export type JsonSchema = {
  type?: string | string[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  default?: unknown;
  description?: string;
  enum?: unknown[];
  items?: JsonSchema;
  [key: string]: unknown;
};

export interface ActionSpec {
  name: string;
  title: string;
  description: string;
  input_schema: JsonSchema;
  side_effect: boolean;
  requires_approval?: boolean;
}

export type ConnectionStatus = "active" | "error" | "demo" | "revoked";

export interface Connection {
  id: string;
  connector_key: string;
  connector_name: string;
  category: Category | null;
  auth_type: AuthType | null;
  name: string;
  status: ConnectionStatus;
  demo: boolean;
  missing_env: string[];
  config: Record<string, unknown>;
  scopes: string[];
  agent_id: string | null;
  error: string | null;
  has_credentials: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  webhook_url: string | null;
  sync_count: number | null;
}

export interface TestResponse {
  ok: boolean;
  message: string;
  details: Record<string, unknown>;
  status: ConnectionStatus;
}

export interface ActionResponse {
  action: string;
  side_effect: boolean;
  demo: boolean;
  elapsed_ms: number;
  result: unknown;
}

export interface OAuthStartResponse {
  mode: "oauth" | "demo";
  url?: string;
  connection?: Connection;
  missing_env?: string[];
}

export type SyncStatus = "idle" | "queued" | "running" | "success" | "error";

export interface SyncRunStats {
  status?: SyncStatus;
  mode?: "full" | "incremental";
  files?: number;
  files_ingested?: number;
  files_failed?: number;
  skipped?: number;
  pruned?: number;
  rows?: number;
  rows_upserted?: number;
  duration_ms?: number;
  finished_at?: string;
  file_errors?: { external_id: string; filename: string; error: string }[];
}

export interface SyncItem {
  id: string;
  connection_id: string;
  connection_name: string | null;
  connector_key: string | null;
  kb_id: string;
  kb_name: string | null;
  resource: string;
  mode: "full" | "incremental";
  cursor_field: string | null;
  cursor: string | null;
  primary_key: string[];
  schedule: string | null;
  options: Record<string, unknown>;
  status: SyncStatus;
  last_run_at: string | null;
  next_run_at: string | null;
  last_error: string | null;
  stats: { last_run?: SyncRunStats; totals?: { runs?: number; errors?: number; files?: number; rows?: number } };
  created_at: string;
  updated_at: string;
}

export interface Resource {
  id: string;
  name: string;
  kind: string;
  has_children: boolean;
  parent: string | null;
  meta: {
    primary_key?: string[];
    cursor_field?: string;
    row_estimate?: number;
    columns?: { name: string; type: string; kb_type: string }[];
    [key: string]: unknown;
  };
}

export interface SchemaColumn {
  name: string;
  type: string;
  kb_type: string;
  nullable: boolean;
  default: string | null;
  comment: string | null;
  pk: boolean;
}

export interface SchemaTable {
  schema: string;
  name: string;
  kind: "table" | "view" | "materialized_view" | "foreign_table";
  comment: string | null;
  row_estimate: number;
  columns: SchemaColumn[];
  primary_key: string[];
  foreign_keys: { name: string; columns: string[]; ref_schema: string; ref_table: string; ref_columns: string[] }[];
}

export interface SchemaDoc {
  dialect: string;
  tables: SchemaTable[];
  table_count: number;
}

export interface WebhookInfo {
  url: string;
  secret: string;
  verification: "hmac" | "token";
  signature_header: string;
  timestamp_header: string;
}

export interface WebhookEvent {
  id: string;
  event: string;
  occurred_at: string | null;
  data: { payload: unknown; headers: Record<string, string>; query: Record<string, string>; source_ip: string | null };
}

export interface McpTool {
  name: string;
  title: string | null;
  description: string | null;
  input_schema: JsonSchema;
  annotations: Record<string, unknown>;
  read_only: boolean;
  side_effect: boolean;
}

export interface AgentItem {
  id: string;
  name: string;
  status: "pending" | "online" | "offline";
  version: string | null;
  hostname: string | null;
  capabilities: { sources?: { name: string; type: string }[]; paths?: string[]; platform?: string };
  last_seen_at: string | null;
  enrolled_at: string | null;
  created_at: string;
  connections: number;
}

export interface EnrollmentResponse {
  agent?: AgentItem;
  enrollment_token: string;
  commands: { binary: string; python: string; docker: string; run: string };
  expires_in_s: number;
}

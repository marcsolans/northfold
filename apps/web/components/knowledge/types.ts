/** Types of the /api/v1/knowledge-bases API (see apps/api/src/messer_api/services/knowledge/schemas.py). */

export type GovernanceMode = "off" | "shadow" | "enforce";
export type SearchMode = "vector" | "keyword" | "hybrid";
export type FileStatus = "queued" | "parsing" | "chunking" | "embedding" | "indexing" | "ready" | "error";
export type LogicalType = "text" | "integer" | "numeric" | "boolean" | "date" | "timestamp" | "json";
export type PolicyRole = "viewer" | "builder" | "admin" | "owner" | "agent" | "*";

export const LOGICAL_TYPES: LogicalType[] = ["text", "integer", "numeric", "boolean", "date", "timestamp", "json"];
export const POLICY_ROLES: PolicyRole[] = ["viewer", "builder", "admin", "owner", "agent", "*"];
export const DOCUMENTS_TABLE = "*documents*";

export interface KbStats {
  files: number;
  files_ready: number;
  files_processing: number;
  files_error: number;
  size: number;
  chunks: number;
  tables: number;
}

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  project_id: string | null;
  embedding_model: string;
  embedding_dim: number;
  governance_mode: GovernanceMode;
  schema_name: string;
  chunk_size_tokens: number;
  chunk_overlap_tokens: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  stats: KbStats;
}

export interface EmbeddingModel {
  id: string;
  dim: number;
  kind: "local" | "offline" | "bedrock" | "voyage" | string;
  available: boolean;
  default: boolean;
}

export interface KbFile {
  id: string;
  kb_id: string;
  filename: string;
  mime: string;
  size: number;
  source: string;
  status: FileStatus;
  error: string | null;
  pages: number | null;
  chunk_count: number;
  table_id: string | null;
  external_id: string | null;
  connection_id: string | null;
  metadata: Record<string, unknown>;
  uploaded_by: string | null;
  created_at: string;
}

export interface FileList {
  items: KbFile[];
  total: number;
}

export interface UploadResult {
  files: KbFile[];
  errors: { filename: string; code: string; message: string }[];
}

export interface KbChunk {
  id: string;
  file_id: string;
  filename: string;
  ordinal: number;
  content: string;
  heading: string | null;
  page_from: number | null;
  page_to: number | null;
  token_count: number;
  metadata: Record<string, unknown>;
  edited_at: string | null;
  has_embedding: boolean;
}

export interface ChunkList {
  items: KbChunk[];
  total: number;
}

export interface SearchHit {
  chunk_id: string;
  file_id: string;
  filename: string;
  content: string;
  heading: string | null;
  page_from: number | null;
  page_to: number | null;
  score: number;
  metadata: Record<string, unknown>;
}

export interface SearchResult {
  hits: SearchHit[];
  mode: SearchMode;
  took_ms: number;
}

export interface PolicyReport {
  mode: GovernanceMode;
  role: string;
  break_glass: boolean;
  applied: { relation: string; masked_columns: Record<string, string>; row_filters: string[] }[];
  would_apply: { relation: string; masked_columns: Record<string, string>; row_filters: string[] }[];
}

export interface QueryResult {
  columns: string[];
  column_types: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
  plan?: unknown;
  policy?: PolicyReport | null;
}

export interface SchemaRelation {
  name: string;
  kind: "table" | "view";
  columns: { name: string; type: string }[];
  row_count: number | null;
  description: string;
}

export interface KbSchema {
  schema_name: string;
  relations: SchemaRelation[];
  functions: string[];
}

export interface TableColumn {
  name: string;
  type: LogicalType;
  nullable: boolean;
  pk: boolean;
  comment: string | null;
  source_name: string | null;
}

export interface KbTable {
  id: string;
  name: string;
  description: string;
  columns: TableColumn[];
  primary_key: string[];
  row_count: number;
  source: string;
  sync_id: string | null;
  file_id: string | null;
  last_load: { rows: number; skipped_rows: number; invalid_values: number; examples: string[] } | null;
  created_at: string;
  updated_at: string;
}

export interface RowsResult {
  columns: { name: string; type: string; pk: boolean; masked: boolean }[];
  rows: unknown[][];
  total: number;
  limit: number;
  offset: number;
  policy: PolicyReport | null;
}

export type FilterOp = "eq" | "neq" | "lt" | "lte" | "gt" | "gte" | "contains" | "starts" | "is_null" | "not_null";

export interface RowFilter {
  column: string;
  op: FilterOp;
  value?: string;
}

export interface KbPolicy {
  id: string;
  table: string;
  role: PolicyRole;
  row_filter_sql: string | null;
  masked_columns: Record<string, string>;
  compliance_tags: string[];
  break_glass: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface EntityRecord {
  table: string;
  pk: Record<string, unknown>;
  values: Record<string, unknown>;
}

export interface KbEntity {
  id: string;
  entity_type: string;
  match_key: string;
  method: "deterministic" | "similarity" | string;
  score: number;
  records: EntityRecord[];
  status: "suggested" | "merged" | "dismissed";
  golden_record: { fields: Record<string, unknown>; sources: { table: string; pk: Record<string, unknown> }[] } | null;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface EntityList {
  items: KbEntity[];
  total: number;
}

export interface KbBackup {
  id: string;
  status: "pending" | "running" | "ready" | "error" | "restoring";
  size: number;
  stats: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  restored_at: string | null;
}

export interface KbEvent {
  type: string;
  file_id?: string;
  filename?: string;
  status?: string;
  progress?: number;
  error?: string;
  chunk_count?: number;
  backup_id?: string;
  chunk_id?: string;
  table_id?: string;
  [key: string]: unknown;
}

/** AgentConfig helpers: defaults (mirroring messer_common.studio.agent_spec), validation and prompt variables. */

import { z } from "zod";

import type { Role } from "@/lib/types";

import type {
  AgentConfig,
  CompactionStrategy,
  ContextFile,
  GuardrailConfig,
  GuardrailType,
  McpApproval,
  McpServerConfig,
  MemberDetail,
  ModelTier,
  PromptVariable,
  ToolCatalogItem,
  ToolConfig,
} from "./types";
import { COMPACTION_STRATEGIES, GUARDRAIL_TYPES, MCP_APPROVALS, MODEL_TIERS } from "./types";

/** Same rule as the API (`^[a-z][a-z0-9_]{0,62}$`). */
export const MEMBER_NAME_RE = /^[a-z][a-z0-9_]{0,62}$/;

export type NameProblem = "empty" | "start" | "chars" | "length" | null;

export function memberNameProblem(name: string): NameProblem {
  if (!name) return "empty";
  if (name.length > 63) return "length";
  if (!/^[a-z]/.test(name)) return "start";
  if (!MEMBER_NAME_RE.test(name)) return "chars";
  return null;
}

/** Builtin tools whose approval policy is fixed by the engine tool factory. */
export const LOCKED_APPROVAL: Record<string, "always" | "non_get"> = {
  send_email: "always",
  http_request: "non_get",
};

/** Same rule as the API for MCP server names. */
export const MCP_NAME_RE = /^[a-z][a-z0-9_]*$/;

/** Project secrets referenced from MCP header values (`Bearer $API_TOKEN`). */
export function secretRefs(value: string): string[] {
  return [...value.matchAll(/\$([A-Z][A-Z0-9_]*)/g)].map((m) => m[1] ?? "").filter(Boolean);
}

const ROLES: Role[] = ["owner", "admin", "builder", "viewer"];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function num(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function normalizeTool(raw: unknown): ToolConfig | null {
  const t = asRecord(raw);
  const type = t.type;
  if (type !== "builtin" && type !== "connector" && type !== "custom") return null;
  const key = str(t.key);
  if (!key) return null;
  const role = ROLES.includes(t.approver_role as Role) ? (t.approver_role as Role) : "admin";
  return {
    type,
    key,
    name: typeof t.name === "string" ? t.name : null,
    connection_id: typeof t.connection_id === "string" ? t.connection_id : null,
    description: str(t.description),
    input_schema: t.input_schema && typeof t.input_schema === "object" ? (t.input_schema as ToolConfig["input_schema"]) : null,
    requires_approval: Boolean(t.requires_approval),
    approver_role: role,
    config: asRecord(t.config),
  };
}

function normalizeGuardrail(raw: unknown): GuardrailConfig | null {
  const g = asRecord(raw);
  if (!GUARDRAIL_TYPES.includes(g.type as GuardrailType)) return null;
  return {
    type: g.type as GuardrailType,
    mode: g.mode === "shadow" ? "shadow" : "enforce",
    topics: Array.isArray(g.topics) ? g.topics.filter((x): x is string => typeof x === "string") : [],
    rubric: str(g.rubric),
  };
}

function normalizeMcp(raw: unknown): McpServerConfig | null {
  const m = asRecord(raw);
  const name = str(m.name);
  if (!name) return null;
  const headers: Record<string, string> = {};
  for (const [k, v] of Object.entries(asRecord(m.headers))) if (typeof v === "string") headers[k] = v;
  return {
    name,
    url: str(m.url),
    headers,
    approval: MCP_APPROVALS.includes(m.approval as McpApproval) ? (m.approval as McpApproval) : "destructive",
  };
}

export function normalizeContextFiles(raw: unknown): ContextFile[] {
  return (Array.isArray(raw) ? raw : [])
    .map((f) => asRecord(f))
    .filter((f) => typeof f.name === "string" && f.name)
    .map((f) => ({ name: str(f.name), mime: str(f.mime, "application/octet-stream"), size: num(f.size, 0) }));
}

/** Fill every field of an AgentConfig from the (possibly partial) JSON stored by the API. */
export function normalizeConfig(member: Pick<MemberDetail, "name" | "description" | "config">): AgentConfig {
  const c = asRecord(member.config);
  const memory = asRecord(c.memory);
  const voice = asRecord(c.voice);
  const tier = MODEL_TIERS.includes(c.model_tier as ModelTier) ? (c.model_tier as ModelTier) : null;
  const model = typeof c.model === "string" && c.model ? c.model : null;
  return {
    name: str(c.name, member.name) || member.name,
    description: str(c.description, member.description),
    model_tier: tier ?? (model ? null : "standard"),
    model,
    system_prompt: str(c.system_prompt),
    variables: (Array.isArray(c.variables) ? c.variables : [])
      .map((v) => asRecord(v))
      .filter((v) => typeof v.name === "string" && v.name)
      .map((v) => ({ name: str(v.name), description: str(v.description), default: str(v.default) })),
    temperature: typeof c.temperature === "number" ? c.temperature : null,
    max_tokens: num(c.max_tokens, 4096),
    max_iter: num(c.max_iter, 10),
    timeout: typeof c.timeout === "number" ? c.timeout : c.timeout === null ? null : 120,
    tools: (Array.isArray(c.tools) ? c.tools : []).map(normalizeTool).filter((t): t is ToolConfig => t !== null),
    knowledge_bases: Array.isArray(c.knowledge_bases)
      ? c.knowledge_bases.filter((x): x is string => typeof x === "string")
      : [],
    context_files: normalizeContextFiles(c.context_files),
    mcp_servers: (Array.isArray(c.mcp_servers) ? c.mcp_servers : [])
      .map(normalizeMcp)
      .filter((m): m is McpServerConfig => m !== null),
    guardrails: (Array.isArray(c.guardrails) ? c.guardrails : [])
      .map(normalizeGuardrail)
      .filter((g): g is GuardrailConfig => g !== null),
    memory: {
      enabled: memory.enabled === undefined ? true : Boolean(memory.enabled),
      compaction: COMPACTION_STRATEGIES.includes(memory.compaction as CompactionStrategy)
        ? (memory.compaction as CompactionStrategy)
        : "tool_results",
      keep_last_n: num(memory.keep_last_n, 20),
    },
    voice: {
      enabled: Boolean(voice.enabled),
      voice: str(voice.voice),
      language: str(voice.language, "es"),
      greeting: str(voice.greeting),
    },
  };
}

/** Stable serialisation used for the dirty-state comparison (context files are saved by their own endpoints). */
export function configFingerprint(config: AgentConfig): string {
  return JSON.stringify({ ...config, context_files: [] });
}

export function builtinTool(item: ToolCatalogItem): ToolConfig {
  return {
    type: "builtin",
    key: item.key,
    name: null,
    connection_id: null,
    description: "",
    input_schema: null,
    requires_approval: item.side_effect || LOCKED_APPROVAL[item.key] === "always",
    approver_role: "admin",
    config: {},
  };
}

export function toolIdentity(tool: Pick<ToolConfig, "type" | "key" | "connection_id">): string {
  return `${tool.type}:${tool.connection_id ?? ""}:${tool.key}`;
}

export function connectorToolName(connectorKey: string, action: string): string {
  const raw = `${connectorKey}_${action}`.toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/_+/g, "_");
  return /^[a-z]/.test(raw) ? raw : `t_${raw}`;
}

export function defaultMcpServer(existing: McpServerConfig[]): McpServerConfig {
  let n = existing.length + 1;
  while (existing.some((m) => m.name === `mcp_${n}`)) n += 1;
  return { name: `mcp_${n}`, url: "https://", headers: {}, approval: "destructive" };
}

export function defaultGuardrail(type: GuardrailType): GuardrailConfig {
  return { type, mode: type === "pii" ? "shadow" : "enforce", topics: [], rubric: "" };
}

// ------------------------------------------------------------------------------------ prompt variables

const VARIABLE_RE = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g;

export function promptVariables(prompt: string): string[] {
  const seen = new Set<string>();
  for (const match of prompt.matchAll(VARIABLE_RE)) {
    if (match[1]) seen.add(match[1]);
  }
  return [...seen];
}

export function isVariableName(value: string): boolean {
  return /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(value);
}

/** Variables used in the prompt that are not declared, and declared ones that are unused. */
export function variableDiagnostics(prompt: string, variables: PromptVariable[]): { undeclared: string[]; unused: string[] } {
  const used = promptVariables(prompt);
  const declared = new Set(variables.map((v) => v.name));
  return {
    undeclared: used.filter((name) => !declared.has(name)),
    unused: variables.map((v) => v.name).filter((name) => !used.includes(name)),
  };
}

// ------------------------------------------------------------------------------------ validation

export type ConfigErrorKey =
  | "model"
  | "temperature"
  | "max_tokens"
  | "max_iter"
  | "timeout"
  | "keep_last_n"
  | "variables"
  | `guardrail.${number}`
  | `tool.${number}`
  | `mcp.${number}`;

export type ConfigErrorCode =
  | "model_format"
  | "temperature_range"
  | "max_tokens_range"
  | "max_iter_range"
  | "timeout_range"
  | "keep_last_n_range"
  | "variable_name"
  | "variable_duplicate"
  | "topics_required"
  | "rubric_required"
  | "mcp_name"
  | "mcp_duplicate"
  | "mcp_url"
  | "mcp_header";

const configSchema = z.object({
  model: z
    .string()
    .regex(/^[a-z0-9_.-]+\/[A-Za-z0-9_.:@-]+$/, "model_format")
    .nullable(),
  temperature: z.number().min(0, "temperature_range").max(1, "temperature_range").nullable(),
  max_tokens: z.number().int("max_tokens_range").min(1, "max_tokens_range").max(200_000, "max_tokens_range"),
  max_iter: z.number().int("max_iter_range").min(1, "max_iter_range").max(100, "max_iter_range"),
  timeout: z.number().int("timeout_range").min(1, "timeout_range").max(3600, "timeout_range").nullable(),
  memory: z.object({
    keep_last_n: z.number().int("keep_last_n_range").min(1, "keep_last_n_range").max(1000, "keep_last_n_range"),
  }),
});

/** Field errors keyed by form field; empty when the configuration can be saved. */
export function validateConfig(config: AgentConfig): Partial<Record<ConfigErrorKey, ConfigErrorCode>> {
  const errors: Partial<Record<ConfigErrorKey, ConfigErrorCode>> = {};
  const parsed = configSchema.safeParse(config);
  if (!parsed.success) {
    for (const issue of parsed.error.issues) {
      const head = issue.path[0];
      const key = (head === "memory" ? "keep_last_n" : String(head)) as ConfigErrorKey;
      if (!errors[key]) errors[key] = issue.message as ConfigErrorCode;
    }
  }
  const names = new Set<string>();
  for (const v of config.variables) {
    if (!isVariableName(v.name)) {
      errors.variables = "variable_name";
      break;
    }
    if (names.has(v.name)) {
      errors.variables = "variable_duplicate";
      break;
    }
    names.add(v.name);
  }
  const mcpNames = new Set<string>();
  config.mcp_servers.forEach((m, i) => {
    let code: ConfigErrorCode | null = null;
    if (!MCP_NAME_RE.test(m.name)) code = "mcp_name";
    else if (mcpNames.has(m.name)) code = "mcp_duplicate";
    else if (!/^https?:\/\/[^\s/]+/.test(m.url)) code = "mcp_url";
    else if (Object.keys(m.headers).some((h) => !/^[A-Za-z0-9-]+$/.test(h))) code = "mcp_header";
    mcpNames.add(m.name);
    if (code) errors[`mcp.${i}`] = code;
  });
  config.guardrails.forEach((g, i) => {
    if (g.type === "topics" && g.topics.length === 0) errors[`guardrail.${i}`] = "topics_required";
    if (g.type === "judge" && !g.rubric.trim()) errors[`guardrail.${i}`] = "rubric_required";
  });
  return errors;
}

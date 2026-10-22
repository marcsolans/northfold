/** Draft helpers for the playbook editor: normalization, new policies, client-side checks, issue lookup. */

import type { ArgConstraint, GuardDetail, Issue, Operator, Playbook, Policy, ToolAction, TurnMatch } from "./types";
import { NUMERIC_OPERATORS } from "./types";

const POLICY_ID = /^[a-z][a-z0-9_-]{0,62}$/;
const FACT = /^[a-z][a-z0-9_-]{0,62}(:[A-Za-z0-9_.\-*]{1,120})?$/;

export function emptyMatch(): TurnMatch {
  return {
    last_message: "any",
    tool_results: [],
    text_patterns: [],
    text_excludes: [],
    min_chars: null,
    max_chars: null,
    first_turn: null,
  };
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map((v) => String(v)) : [];
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizeMatch(raw: Partial<TurnMatch> | undefined): TurnMatch {
  const m = raw ?? {};
  return {
    last_message: m.last_message ?? "any",
    tool_results: strings(m.tool_results),
    text_patterns: strings(m.text_patterns),
    text_excludes: strings(m.text_excludes),
    min_chars: nullableNumber(m.min_chars),
    max_chars: nullableNumber(m.max_chars),
    first_turn: typeof m.first_turn === "boolean" ? m.first_turn : null,
  };
}

function normalizeToolAction(raw: Partial<ToolAction> | null | undefined): ToolAction | null {
  if (!raw) return null;
  return {
    tool: String(raw.tool ?? ""),
    action: raw.action ?? "deny",
    constraints: (raw.constraints ?? []).map((c: Partial<ArgConstraint>) => ({
      arg: String(c.arg ?? ""),
      op: (c.op ?? ">") as Operator,
      value: c.value ?? null,
    })),
    message: raw.message ?? null,
  };
}

export function normalizePolicy(raw: Partial<Policy>): Policy {
  return {
    id: String(raw.id ?? ""),
    description: String(raw.description ?? ""),
    enabled: raw.enabled ?? true,
    condition: raw.condition ?? null,
    match: normalizeMatch(raw.match),
    requires: strings(raw.requires),
    provides: strings(raw.provides),
    model: raw.model ?? null,
    tool_action: normalizeToolAction(raw.tool_action),
    confirmation: raw.confirmation ?? "majority",
    response: raw.response ?? null,
  };
}

export function normalizePlaybook(detail: GuardDetail): Playbook {
  const raw = detail.playbook ?? {};
  return {
    version: raw.version ?? 1,
    enabled: raw.enabled ?? false,
    small_model: raw.small_model ?? detail.defaults.small_model,
    large_model: raw.large_model ?? detail.defaults.large_model,
    policies: (raw.policies ?? []).map((p) => normalizePolicy(p)),
    output_schema: raw.output_schema ?? null,
  };
}

export function emptyPlaybook(detail: GuardDetail): Playbook {
  return {
    version: 1,
    enabled: false,
    small_model: detail.defaults.small_model,
    large_model: detail.defaults.large_model,
    policies: [],
    output_schema: null,
  };
}

export function uniqueId(base: string, taken: string[]): string {
  const clean = base.toLowerCase().replace(/[^a-z0-9_-]/g, "_").replace(/^[^a-z]+/, "") || "politica";
  let id = clean.slice(0, 56);
  let n = 2;
  while (taken.includes(id)) id = `${clean.slice(0, 52)}_${n++}`;
  return id;
}

export function newTurnPolicy(taken: string[]): Policy {
  return normalizePolicy({ id: uniqueId("turno", taken), model: "small", confirmation: "majority" });
}

export function newToolPolicy(taken: string[], tool: string | undefined): Policy {
  return normalizePolicy({
    id: uniqueId(tool ? `${tool}_regla` : "herramienta", taken),
    confirmation: "none",
    tool_action: { tool: tool ?? "", action: "deny", constraints: [], message: null },
  });
}

/** Canonical JSON for the API (and for dirty tracking). */
export function serialize(playbook: Playbook): Playbook {
  return {
    ...playbook,
    policies: playbook.policies.map((p) => ({
      ...p,
      condition: p.condition?.trim() ? p.condition : null,
      response: p.response?.trim() ? p.response : null,
      tool_action: p.tool_action
        ? { ...p.tool_action, message: p.tool_action.message?.trim() ? p.tool_action.message : null }
        : null,
    })),
  };
}

export function fingerprint(playbook: Playbook | null): string {
  return playbook ? JSON.stringify(serialize(playbook)) : "";
}

export function move<T>(items: T[], from: number, to: number): T[] {
  if (to < 0 || to >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(from, 1);
  if (item === undefined) return items;
  next.splice(to, 0, item);
  return next;
}

function validRegex(pattern: string): boolean {
  try {
    new RegExp(pattern);
    return true;
  } catch {
    return false;
  }
}

/** Errors the editor can show before asking the server (the server stays the authority). */
export function clientIssues(playbook: Playbook): Issue[] {
  const issues: Issue[] = [];
  const add = (path: string, code: string) => issues.push({ level: "error", path, code, message: "", params: {} });
  const seen = new Set<string>();
  playbook.policies.forEach((p, i) => {
    const base = `policies.${i}`;
    if (!POLICY_ID.test(p.id)) add(`${base}.id`, "client.invalid_id");
    else if (seen.has(p.id)) add(`${base}.id`, "client.duplicate_id");
    seen.add(p.id);
    [...p.requires, ...p.provides].forEach((f) => {
      if (!FACT.test(f)) add(`${base}.facts`, "client.invalid_fact");
    });
    [...p.match.text_patterns, ...p.match.text_excludes].forEach((pattern) => {
      if (!validRegex(pattern)) add(`${base}.match.text_patterns`, "client.invalid_regex");
    });
    if (p.response && p.tool_action) add(base, "client.response_with_tool");
    if (p.tool_action) {
      if (!p.tool_action.tool.trim()) add(`${base}.tool_action.tool`, "client.required");
      p.tool_action.constraints.forEach((c, k) => {
        const at = `${base}.tool_action.constraints.${k}`;
        if (!c.arg.trim()) add(`${at}.arg`, "client.required");
        if (NUMERIC_OPERATORS.includes(c.op) && typeof c.value !== "number") add(`${at}.value`, "client.number");
        if (c.op === "matches" && (typeof c.value !== "string" || !validRegex(c.value))) add(`${at}.value`, "client.invalid_regex");
      });
    }
  });
  return issues;
}

export function issuesAt(issues: Issue[], prefix: string): Issue[] {
  return issues.filter((i) => i.path === prefix || i.path.startsWith(`${prefix}.`));
}

/** Text shown in the constraint value input. */
export function valueText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map((v) => String(v)).join(", ");
  return String(value);
}

/** Typed constraint value from the input text, per operator. */
export function parseValue(op: Operator, text: string): unknown {
  if (op === "exists" || op === "missing") return null;
  if (op === "in" || op === "not_in") {
    return text
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }
  const trimmed = text.trim();
  if (NUMERIC_OPERATORS.includes(op) || op === "==" || op === "!=") {
    const n = Number(trimmed.replace(",", "."));
    if (trimmed !== "" && Number.isFinite(n)) return n;
  }
  return text;
}

/** "a, b, c" ↔ string[] for list fields. */
export function listText(values: string[]): string {
  return values.join(", ");
}

export function parseList(text: string): string[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

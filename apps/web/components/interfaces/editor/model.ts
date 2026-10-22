/** Pure helpers for the interface editor: defaults, ids, layout (12-column grid) and immutable updates. */

import type { Binding, BindingKind, ComponentDef, ComponentType, Grid, InterfaceDefinition, ScreenDef } from "../types";

export const GRID_COLUMNS = 12;

export const DEFAULT_SIZE: Record<ComponentType, { w: number; h: number }> = {
  data_table: { w: 8, h: 7 },
  chart: { w: 6, h: 6 },
  kpi: { w: 3, h: 2 },
  form: { w: 5, h: 7 },
  chat: { w: 6, h: 9 },
  record_list: { w: 4, h: 7 },
  calendar: { w: 8, h: 8 },
  file_upload: { w: 4, h: 4 },
  action_button: { w: 3, h: 2 },
  approvals_inbox: { w: 6, h: 7 },
};

export const ALLOWED_BINDINGS: Record<ComponentType, BindingKind[]> = {
  data_table: ["knowledge_sql", "knowledge_search", "static"],
  chart: ["knowledge_sql", "static"],
  kpi: ["knowledge_sql", "static"],
  form: ["workflow", "agent"],
  chat: ["agent"],
  record_list: ["knowledge_sql", "knowledge_search", "static"],
  calendar: ["knowledge_sql", "static"],
  file_upload: ["workflow"],
  action_button: ["workflow", "agent"],
  approvals_inbox: ["approvals"],
};

export const BINDING_OPTIONAL: Partial<Record<ComponentType, boolean>> = { file_upload: true };

export interface DefaultsContext {
  agents: string[];
  workflows: string[];
  kbIds: string[];
  title: string;
  label: string;
  fieldLabel: string;
}

export function emptyBinding(kind: BindingKind, ctx: Pick<DefaultsContext, "agents" | "workflows" | "kbIds">): Binding {
  switch (kind) {
    case "knowledge_sql":
      return { kind, kb_id: ctx.kbIds[0] ?? "", sql: "SELECT 1 AS valor", params: [] };
    case "knowledge_search":
      return { kind, kb_ids: ctx.kbIds.slice(0, 1), query: "", query_input: "search", mode: "hybrid", k: 8 };
    case "agent":
      return { kind, workforce: ctx.agents[0] ?? "", prompt: null };
    case "workflow":
      return { kind, workforce: ctx.workflows[0] ?? "", input_mapping: {} };
    case "approvals":
      return { kind, project: "current", status: "pending" };
    default:
      return { kind: "static", data: [] };
  }
}

export function defaultComponent(type: ComponentType, id: string, grid: Grid, ctx: DefaultsContext): ComponentDef {
  const base = { id, type, title: ctx.title, grid };
  switch (type) {
    case "form":
      return {
        ...base,
        props: { fields: [{ name: "nombre", label: ctx.fieldLabel, type: "text", required: true }] },
        binding: emptyBinding(ctx.workflows.length > 0 || ctx.agents.length === 0 ? "workflow" : "agent", ctx),
      };
    case "chat":
      return { ...base, props: { suggestions: [] }, binding: emptyBinding("agent", ctx) };
    case "calendar":
      return { ...base, props: { date_field: "fecha", view: "month" }, binding: { kind: "static", data: [] } };
    case "file_upload":
      return { ...base, props: { kb_id: ctx.kbIds[0] ?? "", accept: [], max_mb: 20, multiple: true }, binding: null };
    case "action_button":
      return {
        ...base,
        props: { label: ctx.label, variant: "primary" },
        binding: emptyBinding(ctx.workflows.length > 0 || ctx.agents.length === 0 ? "workflow" : "agent", ctx),
      };
    case "approvals_inbox":
      return { ...base, props: { page_size: 10 }, binding: emptyBinding("approvals", ctx) };
    case "kpi":
      return { ...base, props: { format: "number" }, binding: { kind: "static", data: [] } };
    default:
      return { ...base, props: {}, binding: { kind: "static", data: [] } };
  }
}

export function nextComponentId(type: ComponentType, definition: InterfaceDefinition): string {
  const taken = new Set(definition.screens.flatMap((s) => s.components.map((c) => c.id)));
  let n = 1;
  while (taken.has(`${type}_${n}`)) n += 1;
  return `${type}_${n}`;
}

export function nextScreenId(definition: InterfaceDefinition): string {
  const taken = new Set(definition.screens.map((s) => s.id));
  let n = definition.screens.length + 1;
  while (taken.has(`pantalla_${n}`)) n += 1;
  return `pantalla_${n}`;
}

export function overlaps(a: Grid, b: Grid): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

export function clampGrid(g: Grid): Grid {
  const w = Math.min(Math.max(1, Math.round(g.w)), GRID_COLUMNS);
  const x = Math.min(Math.max(0, Math.round(g.x)), GRID_COLUMNS - w);
  return { x, y: Math.max(0, Math.round(g.y)), w, h: Math.min(Math.max(1, Math.round(g.h)), 40) };
}

/** Push every component that overlaps the moved one (and, in cascade, the ones they hit) downwards. */
export function resolveCollisions(components: ComponentDef[], movedId: string): ComponentDef[] {
  const list = components.map((c) => ({ ...c, grid: { ...c.grid } }));
  const moved = list.find((c) => c.id === movedId);
  if (!moved) return list;
  const queue: ComponentDef[] = [moved];
  let guard = 0;
  while (queue.length > 0 && guard < 500) {
    guard += 1;
    const anchor = queue.shift() as ComponentDef;
    for (const other of list) {
      if (other.id === anchor.id || other.id === movedId) continue;
      if (overlaps(anchor.grid, other.grid)) {
        other.grid.y = anchor.grid.y + anchor.grid.h;
        queue.push(other);
      }
    }
  }
  return list;
}

/** First free place for a w×h component (top-left first), or below everything. */
export function findSpot(components: ComponentDef[], w: number, h: number): Grid {
  const bottom = components.reduce((max, c) => Math.max(max, c.grid.y + c.grid.h), 0);
  for (let y = 0; y <= bottom; y += 1) {
    for (let x = 0; x + w <= GRID_COLUMNS; x += 1) {
      const g = { x, y, w, h };
      if (!components.some((c) => overlaps(c.grid, g))) return g;
    }
  }
  return { x: 0, y: bottom, w, h };
}

export function mapScreen(
  definition: InterfaceDefinition,
  screenId: string,
  fn: (screen: ScreenDef) => ScreenDef,
): InterfaceDefinition {
  return { ...definition, screens: definition.screens.map((s) => (s.id === screenId ? fn(s) : s)) };
}

export function mapComponent(
  definition: InterfaceDefinition,
  componentId: string,
  fn: (comp: ComponentDef) => ComponentDef,
): InterfaceDefinition {
  return {
    ...definition,
    screens: definition.screens.map((s) => ({
      ...s,
      components: s.components.map((c) => (c.id === componentId ? fn(c) : c)),
    })),
  };
}

export function findComponent(definition: InterfaceDefinition, componentId: string | null): ComponentDef | null {
  if (!componentId) return null;
  for (const s of definition.screens) for (const c of s.components) if (c.id === componentId) return c;
  return null;
}

/** Components whose unsaved definition differs from the saved one (previewed as drafts). */
export function changedComponents(saved: InterfaceDefinition | null, draft: InterfaceDefinition): Record<string, ComponentDef> {
  const before = new Map<string, string>();
  for (const s of saved?.screens ?? []) for (const c of s.components) before.set(c.id, JSON.stringify(c));
  const out: Record<string, ComponentDef> = {};
  for (const s of draft.screens) for (const c of s.components) if (before.get(c.id) !== JSON.stringify(c)) out[c.id] = c;
  return out;
}

/** "screens[0].components[2].binding.sql" → the component id it points to. */
export function componentOfPath(definition: InterfaceDefinition, path: string): string | null {
  const m = /^screens\[(\d+)\]\.components\[(\d+)\]/.exec(path);
  if (!m) return null;
  return definition.screens[Number(m[1])]?.components[Number(m[2])]?.id ?? null;
}

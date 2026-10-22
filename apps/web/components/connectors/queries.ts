"use client";

import { useQuery } from "@tanstack/react-query";

import { ApiError, http } from "@/lib/api";

import type {
  ActionSpec,
  AgentItem,
  CatalogResponse,
  Connection,
  ConnectorItem,
  McpTool,
  SchemaDoc,
  SyncItem,
} from "./types";

export const connectorKeys = {
  catalog: (q: string, category: string) => ["connectors", "catalog", q, category] as const,
  connector: (key: string) => ["connectors", "detail", key] as const,
  connections: ["connections"] as const,
  connection: (id: string) => ["connections", id] as const,
  actions: (id: string) => ["connections", id, "actions"] as const,
  schema: (id: string) => ["connections", id, "schema"] as const,
  tools: (id: string) => ["connections", id, "tools"] as const,
  webhook: (id: string) => ["connections", id, "webhook"] as const,
  webhookEvents: (id: string) => ["connections", id, "webhook-events"] as const,
  resources: (id: string, parent: string | null) => ["connections", id, "resources", parent] as const,
  syncs: (connectionId?: string) => ["syncs", connectionId ?? "all"] as const,
  agents: ["connector-agents"] as const,
};

export function useCatalog(q: string, category: string) {
  return useQuery({
    queryKey: connectorKeys.catalog(q, category),
    queryFn: ({ signal }) =>
      http.get<CatalogResponse>("/connectors", { q: q || undefined, category: category === "all" ? undefined : category }, signal),
    placeholderData: (previous) => previous,
  });
}

export function useConnector(key: string | null | undefined) {
  return useQuery({
    queryKey: connectorKeys.connector(key ?? ""),
    queryFn: () => http.get<ConnectorItem & { actions: ActionSpec[] }>(`/connectors/${key}`),
    enabled: Boolean(key),
    staleTime: 5 * 60_000,
  });
}

export function useConnections() {
  return useQuery({ queryKey: connectorKeys.connections, queryFn: () => http.get<Connection[]>("/connections") });
}

export function useConnection(id: string) {
  return useQuery({
    queryKey: connectorKeys.connection(id),
    queryFn: () => http.get<Connection>(`/connections/${id}`),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });
}

export function useConnectionActions(id: string) {
  return useQuery({ queryKey: connectorKeys.actions(id), queryFn: () => http.get<ActionSpec[]>(`/connections/${id}/actions`) });
}

export function useSchema(id: string, enabled: boolean) {
  return useQuery({
    queryKey: connectorKeys.schema(id),
    queryFn: () => http.get<SchemaDoc>(`/connections/${id}/schema`),
    enabled,
    staleTime: 60_000,
  });
}

export function useMcpTools(id: string, enabled: boolean) {
  return useQuery({
    queryKey: connectorKeys.tools(id),
    queryFn: async () =>
      (await http.post<{ result: McpTool[] }>(`/connections/${id}/actions/list_tools`, { args: {} })).result,
    enabled,
    staleTime: 60_000,
  });
}

export function useSyncs(connectionId?: string) {
  return useQuery({
    queryKey: connectorKeys.syncs(connectionId),
    queryFn: () => http.get<SyncItem[]>("/syncs", { connection_id: connectionId }),
    // Poll while something is queued or running so the status stays live.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((s) => s.status === "queued" || s.status === "running") ? 3000 : false,
  });
}

export function useAgents(live = false) {
  return useQuery({
    queryKey: connectorKeys.agents,
    queryFn: () => http.get<AgentItem[]>("/connector-agents"),
    refetchInterval: live ? 5000 : false,
  });
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

/** Example arguments for an action, built from the JSON Schema defaults and required fields. */
export function exampleArgs(schema: ActionSpec["input_schema"]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const required = new Set(schema.required ?? []);
  for (const [name, prop] of Object.entries(schema.properties ?? {})) {
    if (prop.default !== undefined) out[name] = prop.default;
    else if (required.has(name)) {
      const type = Array.isArray(prop.type) ? prop.type[0] : prop.type;
      if (prop.enum && prop.enum.length > 0) out[name] = prop.enum[0];
      else if (type === "array") out[name] = [];
      else if (type === "object") out[name] = {};
      else if (type === "integer" || type === "number") out[name] = 0;
      else if (type === "boolean") out[name] = false;
      else out[name] = "";
    }
  }
  return out;
}

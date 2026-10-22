"use client";

/** TanStack Query hooks for the workflow builder and triggers. */

import { useQuery } from "@tanstack/react-query";

import { ApiError, http } from "@/lib/api";

import type { ConnectorActionSpec, Palette, Trigger, WorkflowDetail, WorkflowSummary } from "./types";

export const workflowKeys = {
  list: (projectId: string) => ["projects", projectId, "workflows"] as const,
  detail: (projectId: string, name: string) => ["projects", projectId, "workflows", "detail", name] as const,
  palette: (projectId: string) => ["projects", projectId, "workflows", "palette"] as const,
  triggers: (projectId: string) => ["projects", projectId, "triggers"] as const,
  actions: (connectionId: string) => ["connections", connectionId, "actions"] as const,
};

export function workflowPath(projectId: string, name?: string): string {
  return name ? `/projects/${projectId}/workflows/${encodeURIComponent(name)}` : `/projects/${projectId}/workflows`;
}

export function useWorkflows(projectId: string) {
  return useQuery({
    queryKey: workflowKeys.list(projectId),
    queryFn: () => http.get<WorkflowSummary[]>(workflowPath(projectId)),
  });
}

export function useWorkflow(projectId: string, name: string) {
  return useQuery({
    queryKey: workflowKeys.detail(projectId, name),
    queryFn: () => http.get<WorkflowDetail>(workflowPath(projectId, name)),
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
}

export function usePalette(projectId: string) {
  return useQuery({
    queryKey: workflowKeys.palette(projectId),
    queryFn: () => http.get<Palette>(`${workflowPath(projectId)}/palette`),
    staleTime: 60_000,
  });
}

export function useTriggers(projectId: string) {
  return useQuery({
    queryKey: workflowKeys.triggers(projectId),
    queryFn: () => http.get<Trigger[]>(`/projects/${projectId}/triggers`),
    refetchInterval: 30_000,
  });
}

/** Actions of a connection; `null` when the connectors API is not available. */
export function useConnectionActions(connectionId: string | null) {
  return useQuery({
    queryKey: workflowKeys.actions(connectionId ?? "none"),
    enabled: Boolean(connectionId),
    queryFn: async (): Promise<ConnectorActionSpec[] | null> => {
      try {
        return await http.get<ConnectorActionSpec[]>(`/connections/${connectionId}/actions`);
      } catch (err) {
        if (err instanceof ApiError && [403, 404, 405, 501].includes(err.status)) return null;
        throw err;
      }
    },
    staleTime: 5 * 60_000,
  });
}

"use client";

/** TanStack Query hooks for the interfaces API (Studio). */

import { useQuery } from "@tanstack/react-query";

import { ApiError, http } from "@/lib/api";

import type { InterfaceDetail, InterfaceSummary, TemplateInfo, VersionInfo } from "./types";

export const interfaceKeys = {
  list: (projectId: string) => ["projects", projectId, "interfaces"] as const,
  detail: (id: string) => ["interfaces", id] as const,
  versions: (id: string) => ["interfaces", id, "versions"] as const,
  version: (id: string, sha: string) => ["interfaces", id, "versions", sha] as const,
  templates: ["interfaces", "templates"] as const,
  kbs: ["interfaces", "knowledge-bases"] as const,
  tables: (kbId: string) => ["interfaces", "knowledge-bases", kbId, "tables"] as const,
};

export interface KbOption {
  id: string;
  name: string;
  project_id: string | null;
}

export interface KbTableOption {
  id: string;
  name: string;
  columns: { name: string; type: string }[];
  row_count: number;
}

export function useInterfaces(projectId: string) {
  return useQuery({
    queryKey: interfaceKeys.list(projectId),
    queryFn: () => http.get<InterfaceSummary[]>(`/projects/${projectId}/interfaces`),
  });
}

export function useInterface(id: string) {
  return useQuery({ queryKey: interfaceKeys.detail(id), queryFn: () => http.get<InterfaceDetail>(`/interfaces/${id}`) });
}

export function useTemplates() {
  return useQuery({
    queryKey: interfaceKeys.templates,
    queryFn: () => http.get<TemplateInfo[]>("/interfaces/templates"),
    staleTime: 10 * 60_000,
  });
}

export function useVersions(id: string, enabled: boolean) {
  return useQuery({
    queryKey: interfaceKeys.versions(id),
    queryFn: () => http.get<VersionInfo[]>(`/interfaces/${id}/versions`),
    enabled,
  });
}

/** Knowledge bases usable by a project's interfaces (org-wide ones and the project's own). */
export function useKnowledgeBases(projectId: string) {
  return useQuery({
    queryKey: interfaceKeys.kbs,
    queryFn: async () => {
      try {
        const data = await http.get<KbOption[] | { items: KbOption[] }>("/knowledge-bases");
        return Array.isArray(data) ? data : data.items;
      } catch (err) {
        if (err instanceof ApiError && [402, 403, 404].includes(err.status)) return [];
        throw err;
      }
    },
    select: (items) => items.filter((kb) => kb.project_id === null || kb.project_id === projectId),
    staleTime: 60_000,
  });
}

export function useKbTables(kbId: string | null | undefined) {
  return useQuery({
    queryKey: interfaceKeys.tables(kbId ?? ""),
    queryFn: () => http.get<KbTableOption[]>(`/knowledge-bases/${kbId}/tables`),
    enabled: Boolean(kbId),
    staleTime: 60_000,
  });
}

"use client";

import { useQuery } from "@tanstack/react-query";

import { ApiError, http } from "@/lib/api";

import type { EmbeddingModel, KbSchema, KbTable, KnowledgeBase } from "./types";

export const kbKeys = {
  all: ["knowledge-bases"] as const,
  list: (projectId?: string | null) => ["knowledge-bases", "list", projectId ?? null] as const,
  detail: (kbId: string) => ["knowledge-bases", kbId] as const,
  files: (kbId: string) => ["knowledge-bases", kbId, "files"] as const,
  chunks: (kbId: string) => ["knowledge-bases", kbId, "chunks"] as const,
  tables: (kbId: string) => ["knowledge-bases", kbId, "tables"] as const,
  rows: (kbId: string, tableId: string) => ["knowledge-bases", kbId, "tables", tableId, "rows"] as const,
  schema: (kbId: string) => ["knowledge-bases", kbId, "schema"] as const,
  policies: (kbId: string) => ["knowledge-bases", kbId, "policies"] as const,
  entities: (kbId: string) => ["knowledge-bases", kbId, "entities"] as const,
  backups: (kbId: string) => ["knowledge-bases", kbId, "backups"] as const,
  models: ["knowledge-bases", "embedding-models"] as const,
};

export function useKnowledgeBases(projectId?: string | null) {
  return useQuery({
    queryKey: kbKeys.list(projectId),
    queryFn: () => http.get<KnowledgeBase[]>("/knowledge-bases", { project_id: projectId ?? undefined }),
  });
}

export function useKnowledgeBase(kbId: string) {
  return useQuery({
    queryKey: kbKeys.detail(kbId),
    queryFn: () => http.get<KnowledgeBase>(`/knowledge-bases/${kbId}`),
  });
}

export function useKbTables(kbId: string) {
  return useQuery({ queryKey: kbKeys.tables(kbId), queryFn: () => http.get<KbTable[]>(`/knowledge-bases/${kbId}/tables`) });
}

export function useKbSchema(kbId: string) {
  return useQuery({ queryKey: kbKeys.schema(kbId), queryFn: () => http.get<KbSchema>(`/knowledge-bases/${kbId}/schema`) });
}

export function useEmbeddingModels(enabled = true) {
  return useQuery({
    queryKey: kbKeys.models,
    queryFn: () => http.get<EmbeddingModel[]>("/knowledge-bases/embedding-models"),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

export function formatBytes(bytes: number, locale: string): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: value < 10 ? 1 : 0 }).format(value)} ${units[unit]}`;
}

export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

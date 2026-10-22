"use client";

/** TanStack Query hooks and keys for the Studio API. */

import { useQuery } from "@tanstack/react-query";
import * as React from "react";

import { ApiError, http } from "@/lib/api";

import type {
  ApprovalPage,
  ConnectionSummary,
  ConversationSummary,
  CreditsOverview,
  Environment,
  EvalRun,
  KnowledgeBaseSummary,
  Member,
  MemberDetail,
  Project,
  RunDetail,
  RunPage,
  ToolCatalogItem,
  Version,
} from "./types";

export const studioKeys = {
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
  environments: (id: string) => ["projects", id, "environments"] as const,
  members: (id: string, kind?: string) => ["projects", id, "workforce", { kind: kind ?? "all" }] as const,
  member: (id: string, name: string) => ["projects", id, "member", name] as const,
  versions: (id: string, name: string) => ["projects", id, "member", name, "versions"] as const,
  evals: (id: string, name: string) => ["projects", id, "member", name, "evals"] as const,
  conversations: (id: string, name: string) => ["projects", id, "member", name, "conversations"] as const,
  toolsCatalog: (id: string) => ["projects", id, "tools-catalog"] as const,
  runs: (filters: Record<string, string | undefined>) => ["runs", filters] as const,
  run: (id: string) => ["runs", "detail", id] as const,
  approvals: (filters: Record<string, string | boolean | undefined>) => ["approvals", filters] as const,
  pendingApprovals: ["approvals", "pending-count"] as const,
  credits: ["billing", "credits"] as const,
  knowledgeBases: ["knowledge-bases", "picker"] as const,
  connections: ["connections", "picker"] as const,
};

export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

export function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 422);
}

export function useProject(projectId: string) {
  return useQuery({ queryKey: studioKeys.project(projectId), queryFn: () => http.get<Project>(`/projects/${projectId}`) });
}

export function useProjects() {
  return useQuery({ queryKey: studioKeys.projects, queryFn: () => http.get<Project[]>("/projects") });
}

export function useEnvironments(projectId: string) {
  return useQuery({
    queryKey: studioKeys.environments(projectId),
    queryFn: () => http.get<Environment[]>(`/projects/${projectId}/environments`),
  });
}

export function useMembers(projectId: string, kind?: "agent" | "workflow") {
  return useQuery({
    queryKey: studioKeys.members(projectId, kind),
    queryFn: () => http.get<Member[]>(`/projects/${projectId}/workforce`, { kind }),
  });
}

export function useMember(projectId: string, name: string) {
  return useQuery({
    queryKey: studioKeys.member(projectId, name),
    queryFn: () => http.get<MemberDetail>(`/projects/${projectId}/workforce/${encodeURIComponent(name)}`),
    staleTime: 0,
  });
}

export function useVersions(projectId: string, name: string) {
  return useQuery({
    queryKey: studioKeys.versions(projectId, name),
    queryFn: () => http.get<Version[]>(`/projects/${projectId}/workforce/${encodeURIComponent(name)}/versions`),
  });
}

export function useEvalRuns(projectId: string, name: string) {
  return useQuery({
    queryKey: studioKeys.evals(projectId, name),
    queryFn: () => http.get<EvalRun[]>(`/projects/${projectId}/workforce/${encodeURIComponent(name)}/evals`),
  });
}

export function useConversations(projectId: string, name: string) {
  return useQuery({
    queryKey: studioKeys.conversations(projectId, name),
    queryFn: () =>
      http.get<ConversationSummary[]>(`/projects/${projectId}/workforce/${encodeURIComponent(name)}/conversations`),
  });
}

export function useToolsCatalog(projectId: string) {
  return useQuery({
    queryKey: studioKeys.toolsCatalog(projectId),
    queryFn: () => http.get<ToolCatalogItem[]>(`/projects/${projectId}/tools-catalog`),
    staleTime: 5 * 60_000,
  });
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: studioKeys.run(runId),
    queryFn: () => http.get<RunDetail>(`/runs/${runId}`),
    // A run still executing (e.g. a re-run) is polled until it settles.
    refetchInterval: (query) => (query.state.data?.status === "running" ? 3000 : false),
  });
}

export function useRecentRuns(projectId: string, limit = 8) {
  return useQuery({
    queryKey: studioKeys.runs({ project_id: projectId, limit: String(limit), view: "recent" }),
    queryFn: () => http.get<RunPage>("/runs", { project_id: projectId, limit }),
  });
}

export function useCredits() {
  return useQuery({
    queryKey: studioKeys.credits,
    queryFn: () => http.get<CreditsOverview>("/billing/credits"),
    staleTime: 30_000,
  });
}

/** Org-wide pending approvals count (badge in the navigation). */
export function usePendingApprovals() {
  return useQuery({
    queryKey: studioKeys.pendingApprovals,
    queryFn: () => http.get<ApprovalPage>("/approvals", { status: "pending", limit: 1 }),
    refetchInterval: 30_000,
    select: (page) => page.pending,
  });
}

/**
 * Knowledge bases for the agent builder. Resolves to `null` when the knowledge API is not available
 * (the section is then hidden).
 */
export function useKnowledgeBasesOptional() {
  return useQuery({
    queryKey: studioKeys.knowledgeBases,
    queryFn: async (): Promise<KnowledgeBaseSummary[] | null> => {
      try {
        const data = await http.get<KnowledgeBaseSummary[] | { items: KnowledgeBaseSummary[] }>("/knowledge-bases");
        return Array.isArray(data) ? data : data.items;
      } catch (err) {
        if (err instanceof ApiError && [402, 403, 404, 405, 501].includes(err.status)) return null;
        throw err;
      }
    },
    staleTime: 60_000,
  });
}

/** Active (or demo) connections whose actions can be added as tools; `null` when connectors are unavailable. */
export function useConnectionsOptional(enabled: boolean) {
  return useQuery({
    queryKey: studioKeys.connections,
    enabled,
    queryFn: async (): Promise<ConnectionSummary[] | null> => {
      try {
        const data = await http.get<ConnectionSummary[] | { items: ConnectionSummary[] }>("/connections");
        const items = Array.isArray(data) ? data : data.items;
        return items.filter((c) => c.status === "active" || c.status === "demo");
      } catch (err) {
        if (err instanceof ApiError && [402, 403, 404, 405].includes(err.status)) return null;
        throw err;
      }
    },
    staleTime: 60_000,
  });
}

/** Warn before leaving the page (reload, close, internal link) while there are unsaved changes. */
export function useUnsavedChangesGuard(dirty: boolean) {
  const [pendingHref, setPendingHref] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const anchor = (e.target as Element | null)?.closest?.("a[href]");
      if (!(anchor instanceof HTMLAnchorElement) || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
      const url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      e.preventDefault();
      e.stopPropagation();
      setPendingHref(url.pathname + url.search + url.hash);
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty]);
  return { pendingHref, clear: () => setPendingHref(null) };
}

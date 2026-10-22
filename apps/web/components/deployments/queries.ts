"use client";

/** TanStack Query keys and hooks for deployments, environments, project versions and domains. */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { studioKeys } from "@/lib/studio/hooks";
import type { Version } from "@/lib/studio/types";

import { type Deployment, type OrgMember, isActive } from "./types";

export const deploymentKeys = {
  history: (projectId: string, environment?: string) =>
    ["projects", projectId, "deployments", { environment: environment ?? "all" }] as const,
  allHistory: (projectId: string) => ["projects", projectId, "deployments"] as const,
  detail: (id: string) => ["deployments", id] as const,
  versions: (projectId: string) => ["projects", projectId, "project-versions"] as const,
  members: ["members"] as const,
};

/** Poll interval while a deployment is pending, evaluating or deploying. */
export const POLL_MS = 2000;

export function useDeploymentHistory(projectId: string, environment?: string) {
  return useQuery({
    queryKey: deploymentKeys.history(projectId, environment),
    queryFn: () => http.get<Deployment[]>(`/projects/${projectId}/deployments`, { environment, limit: 50 }),
    // Someone else may be publishing: keep the list fresh while anything is in flight.
    refetchInterval: (query) => ((query.state.data ?? []).some((d) => isActive(d.status)) ? POLL_MS * 2 : false),
  });
}

export function useDeployment(id: string, initial?: Deployment) {
  return useQuery({
    queryKey: deploymentKeys.detail(id),
    queryFn: () => http.get<Deployment>(`/deployments/${id}`),
    initialData: initial,
    refetchInterval: (query) => (query.state.data && !isActive(query.state.data.status) ? false : POLL_MS),
  });
}

/** Project-level snapshots that can be deployed, newest first. */
export function useProjectVersions(projectId: string, enabled = true) {
  return useQuery({
    queryKey: deploymentKeys.versions(projectId),
    queryFn: () => http.get<Version[]>(`/projects/${projectId}/versions`),
    enabled,
  });
}

/** Organization members, to show who published. Resolves to an empty list when not readable. */
export function useOrgMembers() {
  return useQuery({
    queryKey: deploymentKeys.members,
    queryFn: () => http.get<OrgMember[]>("/members"),
    staleTime: 5 * 60_000,
  });
}

export function useMemberName() {
  const members = useOrgMembers();
  const byId = React.useMemo(() => new Map((members.data ?? []).map((m) => [m.user_id, m])), [members.data]);
  return React.useCallback(
    (userId: string | null | undefined): string | null => {
      if (!userId) return null;
      const m = byId.get(userId);
      return m ? m.name || m.email : null;
    },
    [byId],
  );
}

/** Refresh everything a finished deployment changes (environments, history, versions, overview). */
export function useInvalidateDeployments(projectId: string) {
  const qc = useQueryClient();
  return React.useCallback(() => {
    void qc.invalidateQueries({ queryKey: studioKeys.environments(projectId) });
    void qc.invalidateQueries({ queryKey: deploymentKeys.allHistory(projectId) });
    void qc.invalidateQueries({ queryKey: deploymentKeys.versions(projectId) });
  }, [qc, projectId]);
}

/** Translated message for a known API error code, the API message otherwise. */
export function useApiErrorText() {
  const t = useTranslations("deployments.errors");
  const tc = useTranslations("common");
  return React.useCallback(
    (err: unknown): string => {
      if (err instanceof ApiError) {
        if (t.has(err.code)) return t(err.code);
        return err.message || tc("errorGeneric");
      }
      if (err instanceof Error && err.message) return err.message;
      return tc("errorGeneric");
    },
    [t, tc],
  );
}

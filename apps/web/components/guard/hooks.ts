"use client";

import { useQuery } from "@tanstack/react-query";

import { http } from "@/lib/api";

import type { GuardDecision, GuardDetail, GuardMetrics } from "./types";

export const guardKeys = {
  detail: (projectId: string, member: string) => ["guard", projectId, member] as const,
  metrics: (projectId: string, member: string, days: number) => ["guard", projectId, member, "metrics", days] as const,
  decisions: (projectId: string, member: string) => ["guard", projectId, member, "decisions"] as const,
  all: (projectId: string, member: string) => ["guard", projectId, member] as const,
};

export function guardPath(projectId: string, member: string, suffix = ""): string {
  return `/projects/${projectId}/guard/${encodeURIComponent(member)}${suffix}`;
}

export function useGuard(projectId: string, member: string) {
  return useQuery({
    queryKey: guardKeys.detail(projectId, member),
    queryFn: () => http.get<GuardDetail>(guardPath(projectId, member)),
  });
}

export function useGuardMetrics(projectId: string, member: string, days: number) {
  return useQuery({
    queryKey: guardKeys.metrics(projectId, member, days),
    queryFn: () => http.get<GuardMetrics>(guardPath(projectId, member, "/metrics"), { days }),
    refetchInterval: 30_000,
  });
}

export function useGuardDecisions(projectId: string, member: string) {
  return useQuery({
    queryKey: guardKeys.decisions(projectId, member),
    queryFn: () => http.get<GuardDecision[]>(guardPath(projectId, member, "/decisions"), { limit: 50 }),
    refetchInterval: 15_000,
  });
}

"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "@/lib/api";
import type { Me, Role } from "@/lib/types";
import { hasRole } from "@/lib/types";

export const ME_KEY = ["me"] as const;

export function useMe() {
  return useQuery({ queryKey: ME_KEY, queryFn: () => http.get<Me>("/me"), staleTime: 60_000 });
}

export function useRole(min: Role): boolean {
  const { data } = useMe();
  return hasRole(data, min);
}

export function useInvalidateMe() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ME_KEY });
}

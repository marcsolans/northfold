"use client";

/** TanStack Query hooks for /api/v1/voice. */

import { useQuery } from "@tanstack/react-query";

import { http } from "@/lib/api";

import type { CallDetail, CallPage, PhoneNumber, VoiceStatus, VoicesResponse } from "./types";

export const voiceKeys = {
  status: ["voice", "status"] as const,
  voices: (language: string) => ["voice", "voices", language] as const,
  calls: (filters: Record<string, string | undefined>) => ["voice", "calls", filters] as const,
  call: (id: string) => ["voice", "call", id] as const,
  numbers: (projectId: string) => ["voice", "numbers", projectId] as const,
};

export function useVoiceStatus() {
  return useQuery({ queryKey: voiceKeys.status, queryFn: () => http.get<VoiceStatus>("/voice/status"), staleTime: 60_000 });
}

export function useVoices(language: string, enabled = true) {
  return useQuery({
    queryKey: voiceKeys.voices(language),
    queryFn: () => http.get<VoicesResponse>("/voice/voices", { language }),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useVoiceCalls(filters: {
  project_id?: string;
  workforce?: string;
  conversation_id?: string;
  phone_number_id?: string;
  transport?: string;
  channel?: "voice" | "phone";
  limit?: string;
}) {
  return useQuery({
    queryKey: voiceKeys.calls(filters),
    queryFn: () => http.get<CallPage>("/voice/calls", filters),
    refetchInterval: (query) =>
      query.state.data?.items.some((c) => ["pending", "ringing", "active"].includes(c.status)) ? 4000 : false,
  });
}

export function useVoiceCall(callId: string | null) {
  return useQuery({
    queryKey: voiceKeys.call(callId ?? ""),
    queryFn: () => http.get<CallDetail>(`/voice/calls/${callId}`),
    enabled: Boolean(callId),
    refetchInterval: (query) => (["pending", "ringing", "active"].includes(query.state.data?.status ?? "") ? 3000 : false),
  });
}

export function usePhoneNumbers(projectId: string) {
  return useQuery({
    queryKey: voiceKeys.numbers(projectId),
    queryFn: () => http.get<PhoneNumber[]>("/voice/numbers", { project_id: projectId }),
  });
}

/** BCP 47 tag for the browser speech APIs ("es" → "es-ES"). */
export function speechLocale(language: string | null | undefined): string {
  const value = (language ?? "es").trim();
  if (value.includes("-")) return value;
  return value === "en" ? "en-US" : value === "es" || !value ? "es-ES" : value;
}

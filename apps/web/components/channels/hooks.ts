"use client";

/** TanStack Query hooks for channels and the conversations inbox, plus live updates over SSE. */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { http } from "@/lib/api";
import { streamSse } from "@/lib/sse";

import type { Channel, ConversationDetail, ProviderInfo } from "./types";

export const channelKeys = {
  all: ["channels"] as const,
  list: (projectId: string) => ["channels", "project", projectId] as const,
  detail: (channelId: string) => ["channels", "detail", channelId] as const,
  messages: (channelId: string) => ["channels", "messages", channelId] as const,
  providers: ["channels", "providers"] as const,
  inbox: (projectId: string) => ["conversations", "inbox", projectId] as const,
  conversation: (id: string) => ["conversations", "detail", id] as const,
};

export function useChannels(projectId: string) {
  return useQuery({
    queryKey: channelKeys.list(projectId),
    queryFn: () => http.get<Channel[]>(`/projects/${projectId}/channels`),
    refetchInterval: 30_000,
  });
}

export function useChannel(channelId: string) {
  return useQuery({
    queryKey: channelKeys.detail(channelId),
    queryFn: () => http.get<Channel>(`/channels/${channelId}`),
    refetchInterval: 30_000,
  });
}

export function useProviders() {
  return useQuery({
    queryKey: channelKeys.providers,
    queryFn: () => http.get<ProviderInfo[]>("/channels/providers"),
    staleTime: 5 * 60_000,
  });
}

export function useConversation(conversationId: string | null, opts: { poll?: boolean } = {}) {
  return useQuery({
    queryKey: channelKeys.conversation(conversationId ?? "none"),
    queryFn: () => http.get<ConversationDetail>(`/conversations/${conversationId}`),
    enabled: Boolean(conversationId),
    // Fallback while the live stream reconnects (or a reply is pending).
    refetchInterval: opts.poll ? 4_000 : 60_000,
  });
}

/**
 * Subscribe to a conversation's live events (messages received and sent, runs finished, status changes)
 * and refresh its queries. Reconnects with backoff; returns whether the stream is connected.
 */
export function useConversationEvents(conversationId: string | null, projectId: string): boolean {
  const qc = useQueryClient();
  const [connected, setConnected] = React.useState(false);

  React.useEffect(() => {
    if (!conversationId) return;
    const controller = new AbortController();
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let pending: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => {
      if (pending) return;
      pending = setTimeout(() => {
        pending = undefined;
        void qc.invalidateQueries({ queryKey: channelKeys.conversation(conversationId) });
        void qc.invalidateQueries({ queryKey: channelKeys.inbox(projectId) });
      }, 150);
    };
    const connect = async () => {
      try {
        await streamSse(`/conversations/${conversationId}/events`, {
          method: "GET",
          signal: controller.signal,
          onMessage: () => {
            attempt = 0;
            refresh();
          },
        });
      } catch {
        // network error or HTTP error: retry below unless unmounted
      }
      if (controller.signal.aborted) return;
      setConnected(false);
      attempt += 1;
      timer = setTimeout(() => void open(), Math.min(30_000, 1_000 * 2 ** Math.min(attempt, 5)));
    };
    const open = async () => {
      setConnected(true);
      refresh();
      await connect();
    };
    void open();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
      if (pending) clearTimeout(pending);
      setConnected(false);
    };
  }, [conversationId, projectId, qc]);

  return connected;
}

/** Credential and config fields offered in the connect form, per provider (non-secret ones are config). */
export const CONFIG_FIELDS: Record<string, string[]> = {
  whatsapp: ["phone_number_id", "business_account_id"],
  slack: [],
  teams: ["app_id", "tenant_id"],
  telegram: [],
  email: ["from_name", "subject_prefix"],
};

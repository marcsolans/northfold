"use client";

import { ChatPanel, type ChatPanelMessage } from "@messer/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import type { DataLabels } from "../labels";
import type { InterfaceSource } from "../source";
import type { ChatEvent, ComponentDef } from "../types";
import { messageOf } from "../util";

let seq = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(seq += 1)}`;

function isAbort(err: unknown): boolean {
  return err instanceof DOMException ? err.name === "AbortError" : err instanceof Error && err.name === "AbortError";
}

/**
 * Chat bound to an agent: streamed answers (sanitized events), per-end-user memory loaded from the server,
 * a notice while an answer waits for a human approval (refreshed until the run resumes) and "new conversation".
 */
export function ChatView({
  comp,
  source,
  labels,
  className,
}: {
  comp: ComponentDef;
  source: InterfaceSource;
  labels: DataLabels;
  className?: string;
}) {
  const t = useTranslations("interfaces");
  const queryClient = useQueryClient();
  const conversationKey = React.useMemo(() => [source.key, "conversation", comp.id], [source.key, comp.id]);
  const [messages, setMessages] = React.useState<ChatPanelMessage[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [activity, setActivity] = React.useState(false);
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);

  const history = useQuery({
    queryKey: conversationKey,
    queryFn: () => source.conversation(comp.id),
    refetchInterval: (q) => (q.state.data && q.state.data.pending_approvals > 0 && !busy ? 10_000 : false),
    staleTime: 0,
  });

  React.useEffect(() => {
    if (!history.data || busy) return;
    setMessages(
      history.data.messages.map((m, i) => ({ id: `h-${i}-${m.at ?? ""}`, role: m.role, text: m.text })),
    );
    setPending(history.data.pending_approvals > 0);
  }, [history.data, busy]);

  React.useEffect(() => () => abortRef.current?.abort(), []);

  const send = async (text: string) => {
    const answerId = nextId("a");
    setError(null);
    setPending(false);
    setMessages((list) => [...list, { id: nextId("u"), role: "user", text }, { id: answerId, role: "assistant", text: "", streaming: true }]);
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;
    let segment = 0;
    const patch = (fn: (m: ChatPanelMessage) => ChatPanelMessage) =>
      setMessages((list) => list.map((m) => (m.id === answerId ? fn(m) : m)));
    const onEvent = (event: ChatEvent) => {
      switch (event.type) {
        case "TEXT":
          setActivity(false);
          patch((m) => {
            const sep = event.segment !== segment && m.text ? "\n\n" : "";
            segment = event.segment;
            return { ...m, text: m.text + sep + event.text };
          });
          break;
        case "ACTIVITY":
          setActivity(true);
          break;
        case "APPROVAL_PENDING":
          setPending(true);
          break;
        case "ERROR":
          patch((m) => ({ ...m, error: event.message || t("data.chatError") }));
          break;
        case "DONE":
          setActivity(false);
          if (event.status === "paused") setPending(true);
          else if (event.status !== "success") patch((m) => ({ ...m, error: m.error ?? (event.message || t("data.chatError")) }));
          break;
        default:
          break;
      }
    };
    try {
      await source.chat(comp.id, text, onEvent, controller.signal);
    } catch (err) {
      if (!isAbort(err)) patch((m) => ({ ...m, error: messageOf(err, t("data.chatError")) }));
    } finally {
      patch((m) => ({ ...m, streaming: false }));
      setBusy(false);
      setActivity(false);
      abortRef.current = null;
      void queryClient.invalidateQueries({ queryKey: conversationKey });
    }
  };

  const reset = async () => {
    try {
      await source.resetConversation(comp.id);
      setMessages([]);
      setPending(false);
      setError(null);
      await queryClient.invalidateQueries({ queryKey: conversationKey });
    } catch (err) {
      setError(messageOf(err, t("data.chatError")));
    }
  };

  const p = comp.props;
  return (
    <ChatPanel
      className={className}
      messages={messages}
      greeting={typeof p.greeting === "string" ? p.greeting : null}
      placeholder={typeof p.placeholder === "string" ? p.placeholder : null}
      suggestions={Array.isArray(p.suggestions) ? (p.suggestions as string[]) : []}
      busy={busy}
      activity={activity}
      approvalPending={pending}
      loading={history.isPending}
      notice={
        error || history.error ? (
          <p role="alert" className="text-sm text-danger">
            {error ?? messageOf(history.error, t("data.chatError"))}
          </p>
        ) : null
      }
      onSend={(text) => void send(text)}
      onStop={() => abortRef.current?.abort()}
      onReset={() => void reset()}
      labels={labels.chat}
    />
  );
}

"use client";

import { Alert, Button, Card, EmptyState, ErrorState, Field, Input, Kbd, SkeletonRows, Spinner, Textarea, toast } from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, Send, Smartphone } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { useMe } from "@/lib/hooks/use-me";
import { errorMessage } from "@/lib/studio/hooks";

import { channelKeys, useConversation, useConversationEvents } from "./hooks";
import { ProviderIcon, useProviderLabel } from "./provider-icon";
import { Thread } from "./thread";
import type { Channel, ConversationDetail, ConversationPage, SimulateResult } from "./types";

const SLOW_QUEUE_MS = 20_000;

function contactKey(value: string): string {
  return value.startsWith("sim:") ? value : `sim:${value}`;
}

function pendingReply(conv: ConversationDetail | undefined): "queued" | "processing" | null {
  const last = conv?.messages.at(-1);
  if (!last || last.role !== "user") return null;
  if (last.delivery?.status === "received") return "queued";
  if (last.delivery?.status === "processing") return "processing";
  return null;
}

/** Chat with the agent as a user of the channel. Replies are stored on the conversation, never sent. */
export function Simulator({ channel, projectId, canBuild }: { channel: Channel; projectId: string; canBuild: boolean }) {
  const t = useTranslations("channels.simulator");
  const tc = useTranslations("common");
  const label = useProviderLabel();
  const qc = useQueryClient();
  const me = useMe();
  const defaultFrom = me.data ? `sim:${me.data.id.replace(/-/g, "").slice(0, 8)}` : "";
  const [from, setFrom] = React.useState("");
  const [name, setName] = React.useState("");
  const [text, setText] = React.useState("");
  const [conversationId, setConversationId] = React.useState<string | null>(null);
  const [poll, setPoll] = React.useState(false);
  const [sentAt, setSentAt] = React.useState<number | null>(null);
  const [now, setNow] = React.useState(() => Date.now());
  const effective = (from.trim() || defaultFrom).slice(0, 120);
  const contact = effective ? contactKey(effective) : "";

  const existing = useQuery({
    queryKey: [...channelKeys.inbox(projectId), "simulator", channel.id, contact],
    queryFn: () => http.get<ConversationPage>(`/projects/${projectId}/conversations`, { channel_id: channel.id, contact, limit: 1 }),
    enabled: Boolean(contact) && conversationId === null,
  });
  const activeId = conversationId ?? existing.data?.items[0]?.id ?? null;
  const conv = useConversation(activeId, { poll });
  const live = useConversationEvents(activeId, projectId);
  const pending = pendingReply(conv.data);

  React.useEffect(() => setPoll(pending !== null || !live), [pending, live]);
  React.useEffect(() => {
    if (pending !== "queued") return;
    const timer = setInterval(() => setNow(Date.now()), 2_000);
    return () => clearInterval(timer);
  }, [pending]);

  const bottom = React.useRef<HTMLDivElement>(null);
  const count = conv.data?.messages.length ?? 0;
  React.useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [count, pending]);

  const send = useMutation({
    mutationFn: (message: string) =>
      http.post<SimulateResult>(`/channels/${channel.id}/simulate`, { from: effective, name: name.trim() || null, text: message }),
    onSuccess: (res) => {
      setText("");
      setSentAt(Date.now());
      setConversationId(res.conversation_id);
      void qc.invalidateQueries({ queryKey: channelKeys.conversation(res.conversation_id) });
      void qc.invalidateQueries({ queryKey: channelKeys.inbox(projectId) });
    },
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const submit = () => {
    const message = text.trim();
    if (!message || send.isPending || !canBuild) return;
    send.mutate(message);
  };

  const restart = () => {
    setFrom(`sim:${Math.random().toString(36).slice(2, 10)}`);
    setConversationId(null);
    setSentAt(null);
  };

  const disabled = channel.status === "disabled";
  const slowQueue = pending === "queued" && sentAt !== null && now - sentAt > SLOW_QUEUE_MS;
  const agentName = channel.workforce_name ?? t("agent");
  const contactName = name.trim() || conv.data?.contact_name || effective;

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      <Card className="flex flex-col gap-3 self-start p-4">
        <div className="flex items-center gap-2">
          <ProviderIcon provider={channel.provider} />
          <div>
            <p className="text-sm font-semibold">{t("title", { provider: label(channel.provider) })}</p>
            <p className="text-xs text-fg-muted">{t("subtitle")}</p>
          </div>
        </div>
        <Field label={t("from")} htmlFor="sim-from" hint={t("fromHint")}>
          <Input
            id="sim-from"
            value={from}
            placeholder={defaultFrom}
            maxLength={120}
            className="font-mono"
            onChange={(e) => {
              setFrom(e.target.value);
              setConversationId(null);
            }}
          />
        </Field>
        <Field label={t("name")} htmlFor="sim-name" hint={tc("optional")}>
          <Input id="sim-name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Button variant="secondary" onClick={restart}>
          <MessageSquarePlus />
          {t("newConversation")}
        </Button>
        <p className="text-xs text-fg-muted">{channel.demo ? t("demoNote") : t("liveNote")}</p>
      </Card>

      <Card className="flex min-h-[28rem] flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto p-4" aria-live="polite">
          {!activeId ? (
            existing.isLoading ? (
              <SkeletonRows rows={4} />
            ) : (
              <EmptyState icon={<Smartphone />} title={t("emptyTitle")} description={t("emptyDescription")} />
            )
          ) : conv.isLoading ? (
            <SkeletonRows rows={4} />
          ) : conv.error ? (
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void conv.refetch()} retryLabel={tc("retry")} />
          ) : conv.data ? (
            <>
              <Thread
                messages={conv.data.messages}
                projectId={projectId}
                perspective="user"
                demo={channel.demo}
                agentName={agentName}
                contactName={contactName}
              />
              {pending ? (
                <p className="mt-3 flex items-center gap-2 text-xs text-fg-muted">
                  <Spinner className="size-3" />
                  {pending === "processing" ? t("typing", { agent: agentName }) : t("queued")}
                </p>
              ) : null}
              {slowQueue ? (
                <Alert tone="warning" className="mt-3">
                  {t("slowQueue")}
                </Alert>
              ) : null}
            </>
          ) : null}
          <div ref={bottom} />
        </div>
        <form
          className="flex items-end gap-2 border-t border-border p-3"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <label htmlFor="sim-text" className="sr-only">
            {t("message")}
          </label>
          <Textarea
            id="sim-text"
            rows={2}
            value={text}
            maxLength={4000}
            disabled={disabled || !canBuild}
            placeholder={disabled ? t("disabled") : canBuild ? t("placeholder") : t("readOnly")}
            className="min-h-[2.5rem] flex-1 resize-none"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <Button type="submit" variant="primary" loading={send.isPending} disabled={disabled || !canBuild || !text.trim()}>
            <Send />
            {t("send")}
          </Button>
        </form>
        <p className="px-3 pb-2 text-[11px] text-fg-subtle">
          <Kbd>Enter</Kbd> {t("sendHint")} · <Kbd>Shift</Kbd>+<Kbd>Enter</Kbd> {t("newLine")}
        </p>
      </Card>
    </div>
  );
}

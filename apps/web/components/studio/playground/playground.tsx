"use client";

import { Alert, Button, ConfirmDialog, ErrorState, Select, SkeletonRows, toast } from "@messer/ui";
import { useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, MessagesSquare, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatRelative, localeTag } from "@/lib/format";
import { type ApprovalPart, chatReducer, initialChat, isStreaming, nextKey } from "@/lib/studio/chat";
import { formatCredits, sameId } from "@/lib/studio/format";
import { errorMessage, studioKeys, useConversations, useCredits } from "@/lib/studio/hooks";
import { type StreamEvent, chatStream, decisionStream, isAbortError } from "@/lib/studio/stream";
import type { Approval, ApprovalPage, Conversation, DecisionBody, Upload } from "@/lib/studio/types";

import { Composer } from "./composer";
import { AssistantTurnView, UserTurnView } from "./turn-view";

export function Playground({
  projectId,
  member,
  canChat,
  unsavedChanges,
}: {
  projectId: string;
  member: string;
  canChat: boolean;
  unsavedChanges: boolean;
}) {
  const t = useTranslations("studio.playground");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const conversations = useConversations(projectId, member);
  const credits = useCredits();
  const [state, dispatch] = React.useReducer(chatReducer, initialChat);
  const stateRef = React.useRef(state);
  React.useEffect(() => {
    stateRef.current = state;
  }, [state]);
  const abortRef = React.useRef<AbortController | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const stickToBottom = React.useRef(true);
  const [loadingConversation, setLoadingConversation] = React.useState(false);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const streaming = isStreaming(state);

  React.useEffect(() => () => abortRef.current?.abort(), []);

  React.useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [state.turns]);

  const afterRun = React.useCallback(() => {
    void qc.invalidateQueries({ queryKey: studioKeys.conversations(projectId, member) });
    void qc.invalidateQueries({ queryKey: studioKeys.credits });
    void qc.invalidateQueries({ queryKey: ["runs"] });
    void qc.invalidateQueries({ queryKey: ["approvals"] });
  }, [qc, projectId, member]);

  /** Fold one SSE stream into the turn `turnKey`. Returns whether the stream finished normally. */
  const runStream = React.useCallback(
    async (
      turnKey: string,
      start: (onEvent: (e: StreamEvent) => void, signal: AbortSignal) => Promise<void>,
      onFailure?: (err: unknown, sawEvents: boolean) => boolean,
    ) => {
      const controller = new AbortController();
      abortRef.current = controller;
      let sawEvents = false;
      try {
        await start((event) => {
          sawEvents = true;
          dispatch({ type: "event", turnKey, event });
        }, controller.signal);
        dispatch({ type: "end", turnKey });
      } catch (err) {
        if (isAbortError(err)) dispatch({ type: "end", turnKey, aborted: true });
        else if (onFailure?.(err, sawEvents)) dispatch({ type: "end", turnKey });
        else {
          dispatch({
            type: "end",
            turnKey,
            error: { message: errorMessage(err, tc("errorGeneric")), code: err instanceof ApiError ? err.code : undefined },
          });
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        afterRun();
      }
    },
    [afterRun, tc],
  );

  const send = (text: string, attachments: Upload[]) => {
    const turnKey = nextKey("turn");
    dispatch({
      type: "send",
      userKey: nextKey("user"),
      turnKey,
      text,
      attachments: attachments.map((a) => a.name),
      at: Date.now(),
    });
    stickToBottom.current = true;
    const conversationId = stateRef.current.conversationId;
    void runStream(turnKey, (onEvent, signal) =>
      chatStream(projectId, member, { message: text, conversation_id: conversationId, attachments: attachments.map((a) => a.id) }, onEvent, signal),
    );
  };

  const decide = (part: ApprovalPart, body: DecisionBody) => {
    const approvalId = part.approvalId;
    if (!approvalId || streaming) return;
    dispatch({ type: "approval_deciding", approvalId, decision: body.decision });
    const turnKey = nextKey("resume");
    dispatch({ type: "resume_start", turnKey, approvalId, at: Date.now() });
    stickToBottom.current = true;
    void runStream(
      turnKey,
      (onEvent, signal) => decisionStream(approvalId, body, onEvent, signal),
      (err, sawEvents) => {
        if (sawEvents) return false;
        // The decision itself was rejected: show it on the card and drop the empty continuation.
        dispatch({ type: "approval_failed", approvalId, message: errorMessage(err, tc("errorGeneric")) });
        if (err instanceof ApiError && err.status === 409) {
          void http.get<Approval>(`/approvals/${approvalId}`).then(
            (approval) => dispatch({ type: "event", turnKey, event: { type: "APPROVAL_RECORDED", approval } }),
            () => undefined,
          );
        }
        return true;
      },
    );
  };

  const stop = () => abortRef.current?.abort();

  const newConversation = () => {
    if (streaming) return;
    setLoadError(null);
    dispatch({ type: "reset" });
  };

  const openConversation = async (id: string) => {
    if (streaming || id === state.conversationId) return;
    setLoadingConversation(true);
    setLoadError(null);
    try {
      const [conversation, pending] = await Promise.all([
        http.get<Conversation>(`/projects/${projectId}/conversations/${id}`),
        http.get<ApprovalPage>("/approvals", { status: "pending", project_id: projectId }),
      ]);
      const runIds = new Set(conversation.messages.map((m) => m.run_id).filter(Boolean));
      if (conversation.last_run_id) runIds.add(conversation.last_run_id);
      const related = pending.items.filter((a) => [...runIds].some((rid) => sameId(rid, a.run_id)));
      stickToBottom.current = true;
      dispatch({ type: "load", conversation, pending: related });
    } catch (err) {
      setLoadError(errorMessage(err, tc("errorGeneric")));
    } finally {
      setLoadingConversation(false);
    }
  };

  const deleteConversation = async () => {
    const id = state.conversationId;
    if (!id) return;
    setDeleting(true);
    try {
      await http.del(`/projects/${projectId}/conversations/${id}`);
      dispatch({ type: "reset" });
      setDeleteOpen(false);
      toast.success(t("conversationDeleted"));
      void qc.invalidateQueries({ queryKey: studioKeys.conversations(projectId, member) });
    } catch (err) {
      toast.error(errorMessage(err, tc("errorGeneric")));
    } finally {
      setDeleting(false);
    }
  };

  const options = (conversations.data ?? []).map((c) => ({
    value: c.id,
    label: c.title || t("untitled"),
    description: `${t("messages", { count: c.message_count })} · ${formatRelative(c.updated_at, locale)}`,
  }));
  if (state.conversationId && !options.some((o) => o.value === state.conversationId)) {
    options.unshift({ value: state.conversationId, label: t("currentConversation"), description: t("justNow") });
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <h2 className="mr-auto flex items-center gap-1.5 text-sm font-semibold">
          <MessagesSquare className="size-4 text-fg-subtle" aria-hidden />
          {t("title")}
        </h2>
        {credits.data ? (
          <span className="tabular text-xs text-fg-muted" title={t("balanceHint")}>
            {t("balance", { value: formatCredits(credits.data.balance, locale) })}
          </span>
        ) : null}
        <div className="w-52">
          <Select
            aria-label={t("conversation")}
            value={state.conversationId ?? undefined}
            placeholder={conversations.isLoading ? tc("loading") : t("pickConversation")}
            disabled={streaming || options.length === 0}
            onValueChange={(id) => void openConversation(id)}
            options={options}
          />
        </div>
        <Button size="sm" variant="secondary" onClick={newConversation} disabled={streaming}>
          <MessageSquarePlus />
          {t("newConversation")}
        </Button>
        {state.conversationId && canChat ? (
          <Button size="icon-sm" variant="ghost" aria-label={t("deleteConversation")} disabled={streaming} onClick={() => setDeleteOpen(true)}>
            <Trash2 />
          </Button>
        ) : null}
      </div>

      {unsavedChanges ? (
        <Alert tone="warning" className="rounded-none border-x-0 border-t-0">
          {t("unsaved")}
        </Alert>
      ) : null}

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-4"
        onScroll={(e) => {
          const el = e.currentTarget;
          stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
        }}
      >
        {loadingConversation ? (
          <SkeletonRows rows={4} />
        ) : loadError ? (
          <ErrorState title={tc("errorTitle")} description={loadError} />
        ) : state.turns.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-1 text-center">
            <p className="text-sm font-medium">{t("emptyTitle")}</p>
            <p className="max-w-xs text-xs text-fg-muted">{t("emptyDescription")}</p>
          </div>
        ) : (
          <div className="flex flex-col gap-5" role="log" aria-live="polite" aria-relevant="additions" aria-label={t("transcript")}>
            {state.turns.map((turn) =>
              turn.role === "user" ? (
                <UserTurnView key={turn.key} turn={turn} />
              ) : (
                <AssistantTurnView key={turn.key} turn={turn} projectId={projectId} onDecide={decide} />
              ),
            )}
          </div>
        )}
      </div>
      <p className="sr-only" aria-live="polite">
        {streaming ? t("streamingStatus") : ""}
      </p>

      <Composer
        projectId={projectId}
        disabled={!canChat}
        disabledReason={canChat ? null : t("needsBuilder")}
        streaming={streaming}
        onSend={send}
        onStop={stop}
      />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={t("deleteConversationTitle")}
        description={t("deleteConversationDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={deleting}
        onConfirm={deleteConversation}
      />
    </div>
  );
}

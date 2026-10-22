"use client";

import { ArrowUp, Hourglass, RotateCcw, Square } from "lucide-react";
import * as React from "react";

import { cn } from "../../lib/cn";
import { Button } from "../button";
import { Skeleton } from "../skeleton";

export interface ChatPanelMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** The answer is still streaming. */
  streaming?: boolean;
  /** Something failed for this answer. */
  error?: string | null;
}

export interface ChatPanelLabels {
  placeholder: string;
  send: string;
  stop: string;
  reset: string;
  working: string;
  approvalPending: string;
  messages: string;
  loading: string;
}

/**
 * Presentational chat: messages, suggestions, composer (Enter or ⌘Enter sends, Shift+Enter adds a line),
 * an activity indicator while tools run and a notice when an answer waits for a human approval.
 * Text is rendered as plain text (never HTML).
 */
export function ChatPanel({
  messages,
  greeting,
  suggestions = [],
  placeholder,
  busy = false,
  activity = false,
  approvalPending = false,
  loading = false,
  disabled = false,
  notice,
  onSend,
  onStop,
  onReset,
  labels,
  className,
}: {
  messages: ChatPanelMessage[];
  greeting?: string | null;
  suggestions?: string[];
  placeholder?: string | null;
  busy?: boolean;
  activity?: boolean;
  approvalPending?: boolean;
  loading?: boolean;
  disabled?: boolean;
  notice?: React.ReactNode;
  onSend: (text: string) => void;
  onStop?: () => void;
  onReset?: () => void;
  labels: ChatPanelLabels;
  className?: string;
}) {
  const [draft, setDraft] = React.useState("");
  const scrollRef = React.useRef<HTMLDivElement | null>(null);
  const inputId = React.useId();

  React.useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, activity, approvalPending]);

  const send = (text: string) => {
    const value = text.trim();
    if (!value || busy || disabled) return;
    onSend(value);
    setDraft("");
  };

  return (
    <div className={cn("flex h-full min-h-0 flex-col", className)}>
      <div
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-label={labels.messages}
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-1 py-2"
      >
        {loading ? (
          <div role="status" aria-label={labels.loading} className="flex flex-col gap-2">
            <Skeleton className="h-10 w-3/4" />
            <Skeleton className="ml-auto h-8 w-1/2" />
          </div>
        ) : null}
        {!loading && greeting ? (
          <div className="max-w-[85%] self-start whitespace-pre-wrap rounded-md border border-border bg-subtle px-3 py-2 text-sm text-fg">
            {greeting}
          </div>
        ) : null}
        {messages.map((m) => (
          <div
            key={m.id}
            className={cn(
              "max-w-[85%] whitespace-pre-wrap break-words rounded-md px-3 py-2 text-sm",
              m.role === "user" ? "self-end bg-fg text-bg" : "self-start border border-border bg-surface text-fg",
              m.error && "border-danger/30 bg-danger-soft text-danger",
            )}
          >
            {m.text || (m.streaming ? <span className="inline-block h-4 w-2 animate-pulse rounded-sm bg-fg-subtle align-middle" aria-hidden /> : null)}
            {m.error && m.text ? <p className="mt-1 text-xs">{m.error}</p> : m.error ? m.error : null}
          </div>
        ))}
        {activity ? (
          <p role="status" className="flex items-center gap-2 self-start text-xs text-fg-muted">
            <span className="inline-block size-2 animate-[messer-pulse-dot_1.4s_ease-in-out_infinite] rounded-full bg-fg-subtle" aria-hidden />
            {labels.working}
          </p>
        ) : null}
        {approvalPending ? (
          <p role="status" className="flex items-start gap-2 self-stretch rounded-md border border-warning/25 bg-warning-soft px-3 py-2 text-sm text-fg">
            <Hourglass className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
            {labels.approvalPending}
          </p>
        ) : null}
      </div>
      {suggestions.length > 0 && messages.length === 0 && !loading ? (
        <div className="flex flex-wrap gap-1.5 pb-2">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              disabled={busy || disabled}
              onClick={() => send(s)}
              className="rounded-full border border-border bg-surface px-3 py-1 text-xs text-fg-muted hover:border-border-strong hover:text-fg disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      ) : null}
      {notice ? <div className="pb-2">{notice}</div> : null}
      <form
        className="flex items-end gap-2 border-t border-border pt-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        {onReset && messages.length > 0 ? (
          <Button type="button" variant="ghost" size="icon" onClick={onReset} disabled={busy} aria-label={labels.reset} title={labels.reset}>
            <RotateCcw />
          </Button>
        ) : null}
        <label htmlFor={inputId} className="sr-only">
          {placeholder || labels.placeholder}
        </label>
        <textarea
          id={inputId}
          value={draft}
          rows={1}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send(draft);
            }
          }}
          placeholder={placeholder || labels.placeholder}
          maxLength={20000}
          className="max-h-40 min-h-9 flex-1 resize-none rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-subtle focus-visible:border-fg-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/20 disabled:opacity-60"
        />
        {busy && onStop ? (
          <Button type="button" variant="secondary" size="icon" onClick={onStop} aria-label={labels.stop} title={labels.stop}>
            <Square />
          </Button>
        ) : (
          <Button type="submit" variant="primary" size="icon" disabled={!draft.trim() || busy || disabled} aria-label={labels.send} title={labels.send}>
            <ArrowUp />
          </Button>
        )}
      </form>
    </div>
  );
}

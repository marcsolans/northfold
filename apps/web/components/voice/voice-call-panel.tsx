"use client";

import { Alert, Badge, Button, Checkbox, ErrorState, Input, Label, Spinner, StatusDot, cn } from "@messer/ui";
import { Mic, MicOff, Phone, PhoneOff, Send, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { formatDuration, formatUsd, localeTag } from "@/lib/format";

import { useVoiceStatus } from "./api";
import type { CallBubble, CallErrorCode, StartOptions, VoiceCallState } from "./use-voice-call";

const ERROR_KEYS: Record<CallErrorCode, string> = {
  mic_denied: "errors.micDenied",
  audio_unsupported: "errors.audioUnsupported",
  speech_unsupported: "errors.speechUnsupported",
  connection_lost: "errors.connectionLost",
  invalid_ticket: "errors.invalidTicket",
  server: "errors.server",
};

function Bubble({ bubble }: { bubble: CallBubble }) {
  const t = useTranslations("voice.call");
  const user = bubble.role === "user";
  return (
    <div className={cn("flex", user ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-md border px-3 py-2 text-sm",
          user ? "border-border bg-subtle text-fg" : "border-border bg-surface text-fg",
          bubble.filler && "border-dashed italic text-fg-muted",
        )}
      >
        <p className="whitespace-pre-wrap">{bubble.text}</p>
        {bubble.interrupted ? <p className="mt-1 text-xs text-fg-subtle">{t("interrupted")}</p> : null}
      </div>
    </div>
  );
}

function ModeBadge({ state }: { state: VoiceCallState }) {
  const t = useTranslations("voice.call");
  const status = useVoiceStatus();
  const mode = state.mode ?? status.data?.mode ?? null;
  if (!mode) return null;
  return mode === "audio" ? (
    <Badge tone="success" title={[state.providers.stt ?? status.data?.audio.stt, state.providers.tts ?? status.data?.audio.tts].filter(Boolean).join(" · ")}>
      {t("modeAudio")}
    </Badge>
  ) : (
    <Badge tone="warning" title={t("modeTextHint")}>
      {t("modeText")}
    </Badge>
  );
}

export function VoiceCallPanel({
  agentName,
  state,
  onStart,
  onHangup,
  onToggleMute,
  onSendText,
  onOpenDetail,
}: {
  agentName: string;
  state: VoiceCallState;
  onStart: (options: StartOptions) => void;
  onHangup: () => void;
  onToggleMute: () => void;
  onSendText: (text: string) => void;
  onOpenDetail?: (callId: string) => void;
}) {
  const t = useTranslations("voice.call");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const status = useVoiceStatus();
  const [record, setRecord] = React.useState(false);
  const [consent, setConsent] = React.useState(false);
  const [typed, setTyped] = React.useState("");
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const live = state.phase === "live" || state.phase === "ending";
  const audioMode = (state.mode ?? status.data?.mode) === "audio";
  const lastMetrics = state.metrics[state.metrics.length - 1];

  React.useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [state.bubbles, state.partial]);

  const submitTyped = (e: React.FormEvent) => {
    e.preventDefault();
    if (!typed.trim()) return;
    onSendText(typed);
    setTyped("");
  };

  const activityLabel =
    state.phase === "connecting"
      ? t("connecting")
      : state.phase === "ending"
        ? t("ending")
        : state.status
          ? state.status
          : state.activity === "thinking"
            ? t("thinking")
            : state.activity === "speaking"
              ? t("speaking")
              : state.muted
                ? t("muted")
                : t("listening");

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="mr-auto text-sm font-medium">{t("withAgent", { agent: agentName })}</p>
        <ModeBadge state={state} />
        {state.recording ? (
          <Badge tone="danger">
            <StatusDot tone="danger" pulse={live} />
            {t("recording")}
          </Badge>
        ) : null}
      </div>

      {(state.mode ?? status.data?.mode) === "text" ? (
        <Alert tone="info" title={t("demoTitle")}>
          {t("demoBody")}
        </Alert>
      ) : null}

      {state.phase === "error" && state.error ? (
        <ErrorState
          title={t("errorTitle")}
          description={state.error.message && state.error.code === "server" ? state.error.message : t(ERROR_KEYS[state.error.code])}
          onRetry={() => onStart({ record, consent })}
          retryLabel={tc("retry")}
        />
      ) : null}

      {state.phase === "idle" || state.phase === "error" ? (
        <div className="space-y-3 rounded-md border border-border p-3">
          <p className="text-sm text-fg-muted">{t("intro")}</p>
          {audioMode ? (
            <div className="space-y-2">
              <div className="flex items-start gap-2">
                <Checkbox id="voice-record" checked={record} onCheckedChange={(v) => setRecord(v === true)} />
                <Label htmlFor="voice-record" className="font-normal">
                  {t("record")}
                </Label>
              </div>
              {record ? (
                <div className="flex items-start gap-2 pl-6">
                  <Checkbox id="voice-consent" checked={consent} onCheckedChange={(v) => setConsent(v === true)} />
                  <Label htmlFor="voice-consent" className="font-normal text-fg-muted">
                    {t("consent")}
                  </Label>
                </div>
              ) : null}
            </div>
          ) : null}
          <Button variant="primary" onClick={() => onStart({ record, consent })} disabled={record && !consent}>
            <Phone />
            {t("start")}
          </Button>
        </div>
      ) : null}

      {state.phase === "connecting" ? (
        <div className="flex items-center gap-2 text-sm text-fg-muted">
          <Spinner />
          {t("connecting")}
        </div>
      ) : null}

      {live || state.phase === "ended" ? (
        <div
          ref={scrollRef}
          className="min-h-48 flex-1 space-y-2 overflow-y-auto rounded-md border border-border bg-bg p-3"
          role="log"
          aria-live="polite"
          aria-label={t("transcript")}
        >
          {state.bubbles.length === 0 && !state.partial ? (
            <p className="text-center text-xs text-fg-subtle">{live ? t("sayHello") : t("noTurns")}</p>
          ) : null}
          {state.bubbles.map((b) => (
            <Bubble key={b.key} bubble={b} />
          ))}
          {state.partial ? (
            <div className="flex justify-end">
              <p className="max-w-[85%] rounded-md border border-dashed border-border px-3 py-2 text-sm text-fg-muted">
                {state.partial}…
              </p>
            </div>
          ) : null}
        </div>
      ) : null}

      {state.approvals.map((a) => (
        <Alert
          key={a.approvalId}
          tone="warning"
          title={t("approvalTitle")}
          action={
            <Button asChild size="sm" variant="secondary">
              <Link href="/app/approvals">{t("approvalOpen")}</Link>
            </Button>
          }
        >
          {a.prompt ?? t("approvalBody")}
        </Alert>
      ))}

      {live ? (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs text-fg-muted" aria-live="polite">
            <StatusDot tone={state.activity === "speaking" ? "accent" : state.activity === "thinking" ? "warning" : "success"} pulse />
            <span className="truncate">{activityLabel}</span>
            {lastMetrics ? (
              <span className="tabular ml-auto shrink-0" title={t("latencyHint")}>
                {t("latency", { value: formatDuration(lastMetrics.eou_to_first_audio_ms) })}
              </span>
            ) : null}
          </div>
          {state.typedInput || state.mode === "text" ? (
            <form className="flex gap-2" onSubmit={submitTyped}>
              <Input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder={state.typedInput ? t("typeInsteadNoMic") : t("typeInstead")}
                aria-label={t("typeInstead")}
              />
              <Button type="submit" size="icon" variant="secondary" aria-label={t("sendTyped")} disabled={!typed.trim()}>
                <Send />
              </Button>
            </form>
          ) : null}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onToggleMute} aria-pressed={state.muted} disabled={state.phase === "ending"}>
              {state.muted ? <MicOff /> : <Mic />}
              {state.muted ? t("unmute") : t("mute")}
            </Button>
            <Button variant="danger" onClick={onHangup} loading={state.phase === "ending"} className="ml-auto">
              <PhoneOff />
              {t("hangup")}
            </Button>
          </div>
        </div>
      ) : null}

      {state.phase === "ended" ? (
        <div className="space-y-2 rounded-md border border-border p-3 text-sm">
          <p className="flex items-center gap-1.5 font-medium">
            <ShieldCheck className="size-4 text-success" aria-hidden />
            {t("ended")}
          </p>
          {state.summary ? (
            <dl className="tabular grid grid-cols-3 gap-2 text-xs">
              <div>
                <dt className="text-fg-subtle">{t("duration")}</dt>
                <dd>{formatDuration(state.summary.duration_ms)}</dd>
              </div>
              <div>
                <dt className="text-fg-subtle">{t("turns")}</dt>
                <dd>{state.summary.turns}</dd>
              </div>
              <div>
                <dt className="text-fg-subtle">{t("cost")}</dt>
                <dd>{formatUsd(Number(state.summary.voice_cost_usd) + Number(state.summary.model_cost_usd), locale)}</dd>
              </div>
            </dl>
          ) : null}
          <div className="flex gap-2">
            {state.callId && onOpenDetail ? (
              <Button size="sm" variant="secondary" onClick={() => onOpenDetail(state.callId as string)}>
                {t("viewCall")}
              </Button>
            ) : null}
            <Button size="sm" variant="primary" onClick={() => onStart({ record, consent })} disabled={record && !consent}>
              <Phone />
              {t("again")}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

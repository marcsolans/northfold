"use client";

import { Alert, Badge, Button, ConfirmDialog, ErrorState, SkeletonRows, Stat, TBody, TD, TH, THead, TR, Table, toast } from "@messer/ui";
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Trash2 } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { apiUrl, http } from "@/lib/api";
import { formatDate, formatDuration, formatNumber, formatUsd, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";
import { errorMessage } from "@/lib/studio/hooks";

import { useVoiceCall, voiceKeys } from "./api";
import type { CallDetail, CallSummary } from "./types";

export function callStatusTone(status: string): "success" | "warning" | "danger" | "neutral" | "info" {
  if (status === "completed") return "success";
  if (status === "active" || status === "ringing" || status === "pending") return "info";
  if (status === "failed") return "danger";
  if (status === "no_answer" || status === "busy" || status === "canceled") return "warning";
  return "neutral";
}

function offset(ms: number | undefined): string {
  if (ms === undefined) return "";
  const total = Math.floor(ms / 1000);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export function CallStatusBadge({ call }: { call: Pick<CallSummary, "status"> }) {
  const t = useTranslations("voice.status");
  return <Badge tone={callStatusTone(call.status)}>{t.has(call.status) ? t(call.status) : call.status}</Badge>;
}

function Recording({ call }: { call: CallDetail }) {
  const t = useTranslations("voice.detail");
  const tc = useTranslations("common");
  const isAdmin = useRole("admin");
  const qc = useQueryClient();
  const [confirm, setConfirm] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  if (!call.has_recording) {
    return <p className="text-sm text-fg-muted">{call.mode === "text" ? t("noRecordingText") : t("noRecording")}</p>;
  }
  const remove = async () => {
    setDeleting(true);
    try {
      await http.del(`/voice/calls/${call.id}/recording`);
      toast.success(t("recordingDeleted"));
      setConfirm(false);
      void qc.invalidateQueries({ queryKey: voiceKeys.call(call.id) });
      void qc.invalidateQueries({ queryKey: ["voice", "calls"] });
    } catch (err) {
      toast.error(errorMessage(err, tc("errorGeneric")));
    } finally {
      setDeleting(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-3">
      <audio controls preload="none" src={apiUrl(`/voice/calls/${call.id}/recording`)} className="h-9 min-w-64 flex-1">
        {t("audioUnsupported")}
      </audio>
      {isAdmin ? (
        <Button size="sm" variant="danger" onClick={() => setConfirm(true)}>
          <Trash2 />
          {t("deleteRecording")}
        </Button>
      ) : null}
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t("deleteRecordingTitle")}
        description={t("deleteRecordingDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        destructive
        loading={deleting}
        onConfirm={remove}
      />
    </div>
  );
}

/** One call as the traces UI shows it: transcript, per-turn latency with links to each run, cost, recording. */
export function VoiceCallDetail({ callId }: { callId: string }) {
  const t = useTranslations("voice.detail");
  const tt = useTranslations("voice.transport");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const query = useVoiceCall(callId);

  if (query.isLoading) return <SkeletonRows rows={6} />;
  if (query.isError || !query.data) {
    return (
      <ErrorState
        title={tc("errorTitle")}
        description={errorMessage(query.error, tc("errorGeneric"))}
        onRetry={() => void query.refetch()}
        retryLabel={tc("retry")}
      />
    );
  }
  const call = query.data;
  const usage = call.usage ?? {};
  const party = call.channel === "phone" ? (call.direction === "inbound" ? call.from_number : call.to_number) : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <CallStatusBadge call={call} />
        <Badge tone="outline">{tt(call.transport)}</Badge>
        <Badge tone={call.mode === "audio" ? "neutral" : "warning"}>{call.mode === "audio" ? t("modeAudio") : t("modeText")}</Badge>
        <span className="text-fg-muted">
          {call.workforce_name}
          {party ? ` · ${party}` : ""}
          {call.started_at ? ` · ${formatDate(call.started_at, locale, true)}` : ""}
        </span>
      </div>

      {call.error ? (
        <Alert tone="danger" title={t("errorTitle")}>
          {call.error.message ?? call.error.code}
        </Alert>
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={t("duration")} value={formatDuration(call.duration_ms)} />
        <Stat label={t("turns")} value={formatNumber(call.turns, locale)} />
        <Stat label={t("firstAudio")} value={formatDuration(call.latency.avg_first_audio_ms ?? null)} hint={t("average")} />
        <Stat
          label={t("cost")}
          value={formatUsd(call.total_cost_usd, locale)}
          hint={t("costSplit", { voice: formatUsd(call.voice_cost_usd, locale), model: formatUsd(call.model_cost_usd, locale) })}
        />
      </div>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">{t("recording")}</h3>
        <Recording call={call} />
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">{t("transcript")}</h3>
        {call.transcript.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("emptyTranscript")}</p>
        ) : (
          <ol className="space-y-1.5">
            {call.transcript.map((entry, i) => (
              <li key={`${entry.timestamp}-${i}`} className="flex gap-3 text-sm">
                <span className="tabular w-12 shrink-0 text-xs text-fg-subtle">{offset(entry.offset_ms)}</span>
                <span className="w-20 shrink-0 text-xs font-medium text-fg-muted">
                  {entry.role === "user" ? t("caller") : t("agent")}
                </span>
                <span className={entry.filler ? "italic text-fg-muted" : undefined}>{entry.text}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">{t("latencyTitle")}</h3>
        {call.turn_details.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("noTurns")}</p>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>#</TH>
                <TH>{t("said")}</TH>
                <TH className="text-right">{t("stt")}</TH>
                <TH className="text-right">{t("llm")}</TH>
                <TH className="text-right">{t("audio")}</TH>
                <TH className="text-right">{t("total")}</TH>
                <TH className="text-right">{t("turnCost")}</TH>
                <TH>
                  <span className="sr-only">{t("trace")}</span>
                </TH>
              </tr>
            </THead>
            <TBody>
              {call.turn_details.map((turn) => (
                <TR key={turn.run_id}>
                  <TD className="tabular text-fg-muted">{turn.turn_index}</TD>
                  <TD className="max-w-56">
                    <p className="truncate" title={turn.user_text}>
                      {turn.user_text}
                    </p>
                    <p className="text-xs text-fg-subtle">
                      {turn.metrics?.interrupted ? t("interrupted") : null}
                      {turn.metrics?.filler_spoken ? ` ${t("filler")}` : null}
                      {turn.status !== "success" ? ` ${turn.status}` : null}
                    </p>
                  </TD>
                  <TD className="tabular text-right">{formatDuration(turn.metrics?.speech_end_to_transcript_ms ?? null)}</TD>
                  <TD className="tabular text-right">{formatDuration(turn.metrics?.eou_to_llm_first_token_ms ?? null)}</TD>
                  <TD className="tabular text-right">{formatDuration(turn.metrics?.eou_to_first_audio_ms ?? null)}</TD>
                  <TD className="tabular text-right">{formatDuration(turn.metrics?.turn_total_ms ?? null)}</TD>
                  <TD className="tabular text-right">{formatUsd(turn.cost_usd, locale)}</TD>
                  <TD>
                    <Button asChild size="icon-sm" variant="ghost" aria-label={t("trace")}>
                      <Link href={`/app/projects/${call.project_id}/traces/${turn.run_id}`}>
                        <ExternalLink />
                      </Link>
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">{t("usage")}</h3>
        <dl className="tabular grid gap-1 text-sm sm:grid-cols-3">
          <div className="rounded-md border border-border px-3 py-2">
            <dt className="text-xs text-fg-subtle">{t("usageStt", { provider: usage.stt?.provider ?? call.stt_provider ?? "—" })}</dt>
            <dd>
              {t("seconds", { value: formatNumber(usage.stt?.seconds ?? 0, locale, 1) })} · {formatUsd(usage.stt?.cost_usd ?? 0, locale)}
            </dd>
          </div>
          <div className="rounded-md border border-border px-3 py-2">
            <dt className="text-xs text-fg-subtle">{t("usageTts", { provider: usage.tts?.provider ?? call.tts_provider ?? "—" })}</dt>
            <dd>
              {t("characters", { value: formatNumber(usage.tts?.characters ?? 0, locale) })} · {formatUsd(usage.tts?.cost_usd ?? 0, locale)}
            </dd>
          </div>
          <div className="rounded-md border border-border px-3 py-2">
            <dt className="text-xs text-fg-subtle">{t("usageLine", { provider: usage.telephony?.provider ?? tt(call.transport) })}</dt>
            <dd>
              {t("seconds", { value: formatNumber(usage.telephony?.seconds ?? 0, locale, 0) })} ·{" "}
              {formatUsd(usage.telephony?.cost_usd ?? 0, locale)}
            </dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

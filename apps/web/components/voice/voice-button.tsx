"use client";

import { Button, ConfirmDialog, Dialog, DialogContent, Sheet, Tooltip, cn } from "@messer/ui";
import { useQueryClient } from "@tanstack/react-query";
import { AudioLines } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { voiceKeys } from "./api";
import { VoiceCallDetail } from "./call-detail";
import type { CallSummaryFrame, VoiceEnvironment } from "./types";
import { useVoiceCall } from "./use-voice-call";
import { VoiceCallPanel } from "./voice-call-panel";

/**
 * Talk to an agent by voice from the browser (Agent builder test chat, public pages, Composer previews).
 * Same tools, rules and memory as the text chat: pass ``conversationId`` to continue that conversation.
 */
export function VoiceButton({
  projectId,
  workforce,
  conversationId,
  environment = "development",
  voiceName,
  disabled = false,
  disabledReason,
  label,
  className,
  onCallEnded,
}: {
  projectId: string;
  workforce: string;
  conversationId?: string | null;
  environment?: VoiceEnvironment;
  /** Browser voice for demo mode (from the agent's ``voice`` setting when it is ``browser:<name>``). */
  voiceName?: string | null;
  disabled?: boolean;
  disabledReason?: string | null;
  /** Show a text label next to the icon. */
  label?: boolean;
  className?: string;
  onCallEnded?: (summary: CallSummaryFrame | null) => void;
}) {
  const t = useTranslations("voice.button");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [confirmClose, setConfirmClose] = React.useState(false);
  const [detailId, setDetailId] = React.useState<string | null>(null);
  const call = useVoiceCall({
    projectId,
    workforce,
    environment,
    conversationId,
    voiceName,
    onEnded: (summary) => {
      void qc.invalidateQueries({ queryKey: ["voice", "calls"] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
      if (summary) void qc.invalidateQueries({ queryKey: voiceKeys.call(summary.call_id) });
      onCallEnded?.(summary);
    },
  });
  const live = ["connecting", "live", "ending"].includes(call.state.phase);

  const onOpenChange = (next: boolean) => {
    if (!next && live) {
      setConfirmClose(true);
      return;
    }
    if (!next && !live) call.reset();
    setOpen(next);
  };

  const trigger = (
    <Button
      variant={live ? "primary" : "secondary"}
      size={label ? "sm" : "icon-sm"}
      onClick={() => setOpen(true)}
      disabled={disabled}
      aria-label={t("open")}
      className={cn(className)}
    >
      <AudioLines />
      {label ? (live ? t("inCall") : t("label")) : null}
    </Button>
  );

  return (
    <>
      {disabled && disabledReason ? <Tooltip content={disabledReason}>{<span>{trigger}</span>}</Tooltip> : <Tooltip content={t("open")}>{trigger}</Tooltip>}
      <Sheet open={open} onOpenChange={onOpenChange} title={t("title", { agent: workforce })} description={t("description")}>
        <VoiceCallPanel
          agentName={workforce}
          state={call.state}
          onStart={(options) => void call.start(options)}
          onHangup={call.hangup}
          onToggleMute={call.toggleMute}
          onSendText={call.sendText}
          onOpenDetail={setDetailId}
        />
      </Sheet>
      <ConfirmDialog
        open={confirmClose}
        onOpenChange={setConfirmClose}
        title={t("hangupTitle")}
        description={t("hangupDescription")}
        confirmLabel={t("hangupConfirm")}
        cancelLabel={tc("cancel")}
        destructive
        onConfirm={() => {
          call.hangup();
          setConfirmClose(false);
          setOpen(false);
        }}
      />
      <Dialog open={detailId !== null} onOpenChange={(o) => (o ? null : setDetailId(null))}>
        {detailId ? (
          <DialogContent title={t("detailTitle")} wide>
            <VoiceCallDetail callId={detailId} />
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}

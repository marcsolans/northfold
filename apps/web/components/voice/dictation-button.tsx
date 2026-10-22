"use client";

import { Button, Tooltip, cn, toast } from "@messer/ui";
import { Mic, Square } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";

import { speechLocale } from "./api";
import { MicCapture, audioSupported } from "./audio";
import { BrowserRecognizer, speechRecognitionAvailable } from "./speech";
import type { TranscriptionTicket } from "./types";

type Phase = "idle" | "starting" | "recording" | "finishing";

/**
 * Dictation for text boxes (the Composer's microphone): the voice module's STT through the voice service when a
 * hosted STT is configured, otherwise the browser's Web Speech API. ``onPartial`` gets the live text of the
 * current utterance, ``onText`` the final text once the user stops.
 */
export function DictationButton({
  onText,
  onPartial,
  language = "es",
  disabled = false,
  className,
}: {
  onText: (text: string) => void;
  onPartial?: (text: string) => void;
  language?: string;
  disabled?: boolean;
  className?: string;
}) {
  const t = useTranslations("voice.dictation");
  const [phase, setPhase] = React.useState<Phase>("idle");
  const socket = React.useRef<WebSocket | null>(null);
  const mic = React.useRef<MicCapture | null>(null);
  const recognizer = React.useRef<BrowserRecognizer | null>(null);
  const finalText = React.useRef<string[]>([]);
  const finishTimer = React.useRef<number | null>(null);
  const [supported, setSupported] = React.useState(true);

  React.useEffect(() => {
    setSupported(audioSupported() || speechRecognitionAvailable());
  }, []);

  const cleanup = React.useCallback(() => {
    if (finishTimer.current !== null) window.clearTimeout(finishTimer.current);
    finishTimer.current = null;
    mic.current?.stop();
    mic.current = null;
    recognizer.current?.stop();
    recognizer.current = null;
    socket.current?.close();
    socket.current = null;
  }, []);

  React.useEffect(() => cleanup, [cleanup]);

  const deliver = React.useCallback(
    (text?: string) => {
      const value = (text ?? finalText.current.join(" ")).trim();
      finalText.current = [];
      cleanup();
      setPhase("idle");
      if (value) onText(value);
    },
    [cleanup, onText],
  );

  const startBrowser = () => {
    if (!speechRecognitionAvailable()) {
      toast.error(t("unsupported"));
      setPhase("idle");
      return;
    }
    const rec = new BrowserRecognizer(speechLocale(language), {
      onPartial: (text) => onPartial?.([...finalText.current, text].join(" ")),
      onFinal: (text) => {
        finalText.current.push(text);
        onPartial?.(finalText.current.join(" "));
      },
      onError: (code) => {
        toast.error(code === "not-allowed" || code === "service-not-allowed" ? t("micDenied") : t("failed"));
        deliver();
      },
    });
    recognizer.current = rec;
    rec.start();
    setPhase("recording");
  };

  const startServer = async (ticket: TranscriptionTicket) => {
    const ws = new WebSocket(ticket.ws_url ?? "");
    ws.binaryType = "arraybuffer";
    socket.current = ws;
    ws.onmessage = (event) => {
      if (typeof event.data !== "string") return;
      let frame: { type: string; text?: string };
      try {
        frame = JSON.parse(event.data) as { type: string; text?: string };
      } catch {
        return;
      }
      if (frame.type === "ready") {
        const capture = new MicCapture((pcm) => {
          if (ws.readyState === WebSocket.OPEN) ws.send(pcm);
        });
        mic.current = capture;
        capture
          .start()
          .then(() => setPhase("recording"))
          .catch(() => {
            toast.error(t("micDenied"));
            deliver();
          });
      } else if (frame.type === "transcript_partial" && frame.text) {
        onPartial?.([...finalText.current, frame.text].join(" "));
      } else if (frame.type === "transcript_committed" && frame.text) {
        finalText.current.push(frame.text);
        onPartial?.(finalText.current.join(" "));
      } else if (frame.type === "done") {
        deliver(frame.text);
      } else if (frame.type === "error") {
        toast.error(t("failed"));
      }
    };
    ws.onclose = (event) => {
      if (event.code === 4409) {
        // The deployment lost its STT key since the ticket: fall back to the browser.
        socket.current = null;
        startBrowser();
        return;
      }
      if (socket.current === ws) deliver();
    };
  };

  const start = async () => {
    setPhase("starting");
    finalText.current = [];
    try {
      const ticket = await http.post<TranscriptionTicket>("/voice/transcriptions", { language });
      if (ticket.mode === "server" && ticket.ws_url && audioSupported()) await startServer(ticket);
      else startBrowser();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : t("failed"));
      setPhase("idle");
    }
  };

  const stop = () => {
    setPhase("finishing");
    mic.current?.stop();
    mic.current = null;
    const ws = socket.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }));
      finishTimer.current = window.setTimeout(() => deliver(), 5000);
      return;
    }
    deliver();
  };

  const recording = phase === "recording" || phase === "starting";
  return (
    <Tooltip content={supported ? (recording ? t("stop") : t("start")) : t("unsupported")}>
      <span className={cn("inline-flex", className)}>
        <Button
          type="button"
          size="icon-sm"
          variant={recording ? "primary" : "ghost"}
          aria-label={recording ? t("stop") : t("start")}
          aria-pressed={recording}
          disabled={disabled || !supported || phase === "finishing"}
          loading={phase === "starting" || phase === "finishing"}
          onClick={() => (recording ? stop() : void start())}
        >
          {recording ? <Square /> : <Mic />}
        </Button>
      </span>
    </Tooltip>
  );
}

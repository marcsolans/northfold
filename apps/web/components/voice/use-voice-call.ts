"use client";

/**
 * One voice call with an agent from the browser: ticket from the API, WebSocket to the voice service, and either
 * hosted audio (mic PCM up, TTS PCM down) or demo text mode (the browser's Web Speech API transcribes and speaks).
 */

import * as React from "react";

import { ApiError, http } from "@/lib/api";

import { speechLocale } from "./api";
import { MicCapture, PcmPlayer, audioSupported } from "./audio";
import { BrowserRecognizer, BrowserSpeaker, speechRecognitionAvailable, speechSynthesisAvailable } from "./speech";
import type { CallSummaryFrame, ServerFrame, TurnMetrics, VoiceEnvironment, VoiceMode, VoiceSessionTicket } from "./types";

export type CallPhase = "idle" | "connecting" | "live" | "ending" | "ended" | "error";
export type CallActivity = "listening" | "thinking" | "speaking";

export interface CallBubble {
  key: string;
  role: "user" | "assistant";
  text: string;
  filler?: boolean;
  interrupted?: boolean;
  runId?: string | null;
}

export interface PendingApproval {
  approvalId: string;
  runId: string;
  prompt: string | null;
}

export type CallErrorCode =
  | "mic_denied"
  | "audio_unsupported"
  | "speech_unsupported"
  | "connection_lost"
  | "invalid_ticket"
  | "server";

export interface VoiceCallState {
  phase: CallPhase;
  activity: CallActivity;
  mode: VoiceMode | null;
  callId: string | null;
  conversationId: string | null;
  recording: boolean;
  bubbles: CallBubble[];
  partial: string;
  status: string | null;
  metrics: TurnMetrics[];
  approvals: PendingApproval[];
  error: { code: CallErrorCode; message: string | null } | null;
  summary: CallSummaryFrame | null;
  muted: boolean;
  typedInput: boolean;
  providers: { stt: string | null; tts: string | null };
}

const initial: VoiceCallState = {
  phase: "idle",
  activity: "listening",
  mode: null,
  callId: null,
  conversationId: null,
  recording: false,
  bubbles: [],
  partial: "",
  status: null,
  metrics: [],
  approvals: [],
  error: null,
  summary: null,
  muted: false,
  typedInput: false,
  providers: { stt: null, tts: null },
};

type Action =
  | { type: "connecting" }
  | { type: "ticket"; ticket: VoiceSessionTicket }
  | { type: "frame"; frame: ServerFrame }
  | { type: "typed_input" }
  | { type: "mute"; muted: boolean }
  | { type: "ending" }
  | { type: "closed" }
  | { type: "fail"; code: CallErrorCode; message?: string | null }
  | { type: "reset" };

let bubbleSeq = 0;
const nextBubbleKey = () => `vb-${++bubbleSeq}`;

function lastAssistantOpen(bubbles: CallBubble[]): number {
  const last = bubbles[bubbles.length - 1];
  return last && last.role === "assistant" && !last.filler && last.runId === undefined ? bubbles.length - 1 : -1;
}

function reduce(state: VoiceCallState, action: Action): VoiceCallState {
  switch (action.type) {
    case "connecting":
      return { ...initial, phase: "connecting" };
    case "ticket":
      return {
        ...state,
        mode: action.ticket.mode,
        callId: action.ticket.call_id,
        conversationId: action.ticket.conversation_id,
        recording: action.ticket.recording,
        providers: { stt: action.ticket.stt, tts: action.ticket.tts },
      };
    case "typed_input":
      return { ...state, typedInput: true };
    case "mute":
      return { ...state, muted: action.muted };
    case "ending":
      return state.phase === "live" ? { ...state, phase: "ending" } : state;
    case "closed":
      return state.phase === "error" ? state : { ...state, phase: "ended", partial: "", status: null };
    case "fail":
      return { ...state, phase: "error", error: { code: action.code, message: action.message ?? null } };
    case "reset":
      return initial;
    case "frame":
      return reduceFrame(state, action.frame);
  }
}

function reduceFrame(state: VoiceCallState, frame: ServerFrame): VoiceCallState {
  switch (frame.type) {
    case "session_started":
      return { ...state, phase: "live", activity: "listening", recording: Boolean(frame.recording) };
    case "transcript_partial":
      return { ...state, partial: frame.text };
    case "transcript_committed": {
      const bubbles = [...state.bubbles];
      const last = bubbles[bubbles.length - 1];
      if (frame.replace && last?.role === "user") bubbles[bubbles.length - 1] = { ...last, text: frame.text };
      else bubbles.push({ key: nextBubbleKey(), role: "user", text: frame.text });
      return { ...state, bubbles, partial: "", activity: "thinking", status: null };
    }
    case "agent_text_delta": {
      const bubbles = [...state.bubbles];
      const open = lastAssistantOpen(bubbles);
      if (open >= 0) {
        const bubble = bubbles[open];
        if (bubble) bubbles[open] = { ...bubble, text: bubble.text + frame.text };
      } else bubbles.push({ key: nextBubbleKey(), role: "assistant", text: frame.text });
      return { ...state, bubbles, activity: "speaking", status: null };
    }
    case "agent_text_done": {
      const bubbles = [...state.bubbles];
      const open = lastAssistantOpen(bubbles);
      if (open >= 0) {
        const bubble = bubbles[open];
        if (bubble) bubbles[open] = { ...bubble, text: frame.text || bubble.text, runId: frame.run_id };
      } else if (frame.text) {
        bubbles.push({ key: nextBubbleKey(), role: "assistant", text: frame.text, runId: frame.run_id });
      }
      return { ...state, bubbles, activity: "listening", status: null };
    }
    case "filler":
      return {
        ...state,
        bubbles: [...state.bubbles, { key: nextBubbleKey(), role: "assistant", text: frame.text, filler: true, runId: null }],
      };
    case "agent_status":
      return { ...state, status: frame.text };
    case "agent_approval":
      return {
        ...state,
        approvals: [...state.approvals, { approvalId: frame.approval_id, runId: frame.run_id, prompt: frame.prompt ?? null }],
      };
    case "metrics":
      return { ...state, metrics: [...state.metrics, frame.metrics] };
    case "interrupted": {
      const bubbles = [...state.bubbles];
      for (let i = bubbles.length - 1; i >= 0; i--) {
        const bubble = bubbles[i];
        if (bubble?.role === "assistant" && !bubble.filler) {
          bubbles[i] = { ...bubble, text: frame.heard_text ?? bubble.text, interrupted: true };
          break;
        }
      }
      return { ...state, bubbles, activity: "listening" };
    }
    case "error":
      if (frame.code) return { ...state, phase: "error", error: { code: frame.code === "invalid_ticket" ? "invalid_ticket" : "server", message: frame.message } };
      return { ...state, error: { code: "server", message: frame.message } };
    case "call_summary":
      return { ...state, summary: frame, conversationId: frame.conversation_id ?? state.conversationId };
    default:
      return state;
  }
}

export interface StartOptions {
  record: boolean;
  consent: boolean;
}

export function useVoiceCall({
  projectId,
  workforce,
  environment = "development",
  conversationId,
  voiceName,
  onEnded,
}: {
  projectId: string;
  workforce: string;
  environment?: VoiceEnvironment;
  conversationId?: string | null;
  /** Browser voice name for demo mode (``browser:<name>`` agent setting). */
  voiceName?: string | null;
  onEnded?: (summary: CallSummaryFrame | null) => void;
}) {
  const [state, dispatch] = React.useReducer(reduce, initial);
  const ws = React.useRef<WebSocket | null>(null);
  const mic = React.useRef<MicCapture | null>(null);
  const player = React.useRef<PcmPlayer | null>(null);
  const recognizer = React.useRef<BrowserRecognizer | null>(null);
  const speaker = React.useRef<BrowserSpeaker | null>(null);
  const ackTimer = React.useRef<number | null>(null);
  const summaryRef = React.useRef<CallSummaryFrame | null>(null);
  const languageRef = React.useRef("es");
  const browserVoiceRef = React.useRef<string | null>(null);
  const onEndedRef = React.useRef(onEnded);
  React.useEffect(() => {
    onEndedRef.current = onEnded;
  }, [onEnded]);

  const send = React.useCallback((payload: Record<string, unknown> | ArrayBuffer) => {
    const socket = ws.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(payload instanceof ArrayBuffer ? payload : JSON.stringify(payload));
  }, []);

  const teardown = React.useCallback(() => {
    if (ackTimer.current !== null) window.clearInterval(ackTimer.current);
    ackTimer.current = null;
    mic.current?.stop();
    mic.current = null;
    player.current?.stop();
    player.current = null;
    recognizer.current?.stop();
    recognizer.current = null;
    speaker.current?.cancel();
    speaker.current = null;
  }, []);

  React.useEffect(
    () => () => {
      teardown();
      ws.current?.close();
      ws.current = null;
    },
    [teardown],
  );

  const handleFrame = React.useCallback(
    (frame: ServerFrame) => {
      if (frame.type === "audio") {
        player.current?.enqueue(frame.data);
        return;
      }
      if (frame.type === "speak") {
        speaker.current?.enqueue({ segment: frame.segment, text: frame.text, durationMs: frame.duration_ms });
        return;
      }
      if (frame.type === "interrupted") {
        if (player.current) {
          player.current.clear();
          send({ type: "playback", played_ms: player.current.playedMs() });
        }
        if (speaker.current) {
          speaker.current.cancel();
          send({ type: "playback", played_ms: speaker.current.playedMs() });
          send({ type: "speech_done" });
        }
      }
      if (frame.type === "transcript_committed" && speaker.current?.speaking()) {
        // The caller took the floor: stop reading the previous reply out loud.
        speaker.current.cancel();
        send({ type: "playback", played_ms: speaker.current.playedMs() });
        send({ type: "speech_done" });
      }
      if (frame.type === "call_summary") summaryRef.current = frame;
      dispatch({ type: "frame", frame });
    },
    [send],
  );

  const startMedia = React.useCallback(
    async (mode: VoiceMode, language: string) => {
      if (mode === "audio") {
        const out = new PcmPlayer();
        await out.start();
        player.current = out;
        const capture = new MicCapture((pcm) => send(pcm));
        mic.current = capture;
        await capture.start();
        let lastPlaying = false;
        ackTimer.current = window.setInterval(() => {
          const playing = out.isPlaying();
          if (playing || lastPlaying) send({ type: "playback", played_ms: out.playedMs() });
          lastPlaying = playing;
        }, 250);
        return;
      }
      const locale = speechLocale(language);
      if (speechSynthesisAvailable()) {
        const voice = new BrowserSpeaker(locale, browserVoiceRef.current, () => {
          send({ type: "playback", played_ms: voice.playedMs() });
          send({ type: "speech_done" });
        });
        speaker.current = voice;
        ackTimer.current = window.setInterval(() => {
          if (voice.speaking()) send({ type: "playback", played_ms: voice.playedMs() });
        }, 250);
      }
      if (!speechRecognitionAvailable()) {
        dispatch({ type: "typed_input" });
        return;
      }
      const rec = new BrowserRecognizer(locale, {
        onPartial: (text) => send({ type: "user_text", text, final: false }),
        onFinal: (text) => send({ type: "user_text", text, final: true }),
        onError: (code) => {
          if (code === "not-allowed" || code === "service-not-allowed") dispatch({ type: "fail", code: "mic_denied" });
          else dispatch({ type: "typed_input" });
        },
      });
      recognizer.current = rec;
      rec.start();
    },
    [send],
  );

  const start = React.useCallback(
    async (options: StartOptions) => {
      if (ws.current) return;
      dispatch({ type: "connecting" });
      summaryRef.current = null;
      let ticket: VoiceSessionTicket;
      try {
        ticket = await http.post<VoiceSessionTicket>("/voice/sessions", {
          project_id: projectId,
          workforce,
          environment,
          conversation_id: conversationId ?? null,
          record: options.record,
          consent: options.consent,
        });
      } catch (err) {
        dispatch({ type: "fail", code: "server", message: err instanceof ApiError ? err.message : null });
        return;
      }
      if (ticket.mode === "audio" && !audioSupported()) {
        dispatch({ type: "fail", code: "audio_unsupported" });
        return;
      }
      dispatch({ type: "ticket", ticket });
      languageRef.current = ticket.language;
      browserVoiceRef.current = voiceName ?? (ticket.voice.startsWith("browser:") ? ticket.voice.slice("browser:".length) : null);
      const socket = new WebSocket(ticket.ws_url);
      socket.binaryType = "arraybuffer";
      ws.current = socket;
      let started = false;
      socket.onmessage = (event) => {
        if (typeof event.data !== "string") return;
        let frame: ServerFrame;
        try {
          frame = JSON.parse(event.data) as ServerFrame;
        } catch {
          return;
        }
        handleFrame(frame);
        if (frame.type === "session_started" && !started) {
          started = true;
          startMedia(ticket.mode, ticket.language).catch((err: unknown) => {
            const denied = err instanceof DOMException && (err.name === "NotAllowedError" || err.name === "SecurityError");
            dispatch({ type: "fail", code: denied ? "mic_denied" : "audio_unsupported" });
            send({ type: "hangup" });
          });
        }
      };
      socket.onerror = () => {
        if (!started) dispatch({ type: "fail", code: "connection_lost" });
      };
      socket.onclose = () => {
        teardown();
        ws.current = null;
        dispatch({ type: "closed" });
        onEndedRef.current?.(summaryRef.current);
      };
    },
    [projectId, workforce, environment, conversationId, voiceName, handleFrame, startMedia, send, teardown],
  );

  const hangup = React.useCallback(() => {
    dispatch({ type: "ending" });
    send({ type: "hangup" });
    teardown();
    // The server replies with call_summary and closes; don't hang forever on a half-open socket.
    window.setTimeout(() => ws.current?.close(), 5000);
  }, [send, teardown]);

  const toggleMute = React.useCallback(() => {
    const next = !state.muted;
    if (mic.current) mic.current.muted = next;
    if (recognizer.current && next) recognizer.current.stop();
    if (!next && state.mode === "text" && recognizer.current === null && speechRecognitionAvailable()) {
      const rec = new BrowserRecognizer(speechLocale(languageRef.current), {
        onPartial: (text) => send({ type: "user_text", text, final: false }),
        onFinal: (text) => send({ type: "user_text", text, final: true }),
        onError: () => dispatch({ type: "typed_input" }),
      });
      recognizer.current = rec;
      rec.start();
    } else if (next) {
      recognizer.current = null;
    }
    dispatch({ type: "mute", muted: next });
  }, [state.muted, state.mode, send]);

  const sendText = React.useCallback((text: string) => {
    const value = text.trim();
    if (value) send({ type: "user_text", text: value, final: true });
  }, [send]);

  const reset = React.useCallback(() => dispatch({ type: "reset" }), []);

  return { state, start, hangup, toggleMute, sendText, reset };
}

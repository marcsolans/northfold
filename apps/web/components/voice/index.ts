/**
 * Voice components (owner: voice workstream).
 *
 * - ``VoiceButton``: call an agent from the browser (Agent builder test chat: pass ``conversationId`` to continue
 *   the text conversation with the same memory).
 * - ``DictationButton``: microphone for text boxes (Composer): voice-module STT or the Web Speech API.
 * - ``VoiceSettingsSection``: Agent builder → Voice (enable, language, voice, opening greeting).
 * - ``PhoneSettings``: Channels → Phone (numbers, agent per number, outbound calls, recent calls).
 * - ``LivekitRoomCard``: LiveKit rooms with the agent in them.
 * - ``VoiceCallsList`` / ``VoiceCallDetail``: call records (transcript, per-turn latency, cost, recording) for the
 *   conversations inbox and traces.
 */

export { VoiceButton } from "./voice-button";
export { VoiceCallPanel } from "./voice-call-panel";
export { DictationButton } from "./dictation-button";
export { VoiceSettingsSection } from "./voice-settings-section";
export { PhoneSettings } from "./phone-settings";
export { LivekitRoomCard } from "./livekit-room";
export { VoiceCallsList } from "./calls-list";
export { CallStatusBadge, VoiceCallDetail } from "./call-detail";
export { useVoiceCall } from "./use-voice-call";
export { useVoiceStatus, useVoiceCalls, useVoiceCall as useVoiceCallRecord, voiceKeys } from "./api";
export type { AgentVoiceConfig, CallDetail, CallSummary, CallSummaryFrame, PhoneNumber, VoiceStatus } from "./types";

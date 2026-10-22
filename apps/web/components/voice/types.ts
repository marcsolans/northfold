/** Voice API (/api/v1/voice) and voice-service WebSocket protocol types. */

export type VoiceMode = "audio" | "text";
export type VoiceEnvironment = "development" | "production";
export type PhoneProvider = "twilio" | "telnyx";

export interface VoiceStatus {
  mode: VoiceMode;
  audio: { available: boolean; stt: string | null; tts: string | null };
  dictation: { mode: "server" | "browser"; stt: string | null };
  telephony: Record<PhoneProvider, boolean>;
  livekit: boolean;
  region: string | null;
  residency: "standard" | "eu_strict" | null;
  missing: { variable: string; feature: "audio" | "phone" | "livekit" }[];
}

export interface VoiceSessionTicket {
  call_id: string;
  conversation_id: string;
  ticket: string;
  ws_url: string;
  expires_in: number;
  mode: VoiceMode;
  language: string;
  voice: string;
  greeting: string;
  stt: string | null;
  tts: string | null;
  recording: boolean;
}

export interface TranscriptionTicket {
  mode: "server" | "browser";
  ticket: string | null;
  ws_url: string | null;
  expires_in: number;
  language: string;
  stt: string | null;
}

export interface TurnMetrics {
  turn_index: number;
  run_id: string | null;
  speech_end_to_transcript_ms: number | null;
  eou_to_llm_first_token_ms: number | null;
  eou_to_first_audio_ms: number | null;
  llm_total_ms: number | null;
  tts_total_ms: number | null;
  turn_total_ms: number;
  interrupted: boolean;
  filler_spoken: boolean;
}

export interface CallTurn {
  turn_index: number;
  run_id: string;
  parent_run_id: string | null;
  status: string;
  user_text: string;
  assistant_text: string;
  cost_usd: string;
  credits: string;
  demo: boolean;
  tools: string[];
  approvals: { id: string | null; tool_name: string | null; title: string | null }[];
  error: { type?: string; message?: string } | null;
  started_ms: number;
  metrics: TurnMetrics | null;
}

export interface TranscriptEntry {
  role: "user" | "assistant";
  text: string;
  timestamp: number;
  offset_ms?: number;
  filler: boolean;
}

export interface CallSummary {
  id: string;
  project_id: string;
  workforce_name: string;
  environment: string;
  conversation_id: string | null;
  phone_number_id: string | null;
  transport: "browser" | "twilio" | "telnyx" | "livekit";
  channel: "voice" | "phone";
  mode: VoiceMode;
  direction: "inbound" | "outbound";
  status: string;
  from_number: string | null;
  to_number: string | null;
  language: string;
  turns: number;
  duration_ms: number | null;
  voice_cost_usd: string;
  model_cost_usd: string;
  total_cost_usd: string;
  has_recording: boolean;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
}

export interface CallUsagePart {
  provider: string | null;
  model?: string | null;
  seconds?: number;
  characters?: number;
  direction?: string;
  cost_usd: string;
}

export interface CallDetail extends CallSummary {
  stt_provider: string | null;
  tts_provider: string | null;
  recording_consent: string | null;
  recording_ms: number | null;
  transcript: TranscriptEntry[];
  turn_details: CallTurn[];
  usage: { stt?: CallUsagePart; tts?: CallUsagePart; telephony?: CallUsagePart; total_usd?: string };
  credits: string;
  error: { code?: string; message?: string } | null;
  latency: Record<string, number | null>;
}

export interface CallPage {
  items: CallSummary[];
  total: number;
}

export interface PhoneNumber {
  id: string;
  project_id: string;
  workforce_name: string;
  environment: VoiceEnvironment;
  provider: PhoneProvider;
  number: string;
  label: string;
  status: string;
  purchased: boolean;
  record_calls: boolean;
  greeting: string;
  error: string | null;
  created_at: string;
}

export interface ProviderNumber {
  provider: PhoneProvider;
  number: string;
  external_id: string;
  label: string;
  locality: string | null;
  country: string | null;
  voice: boolean;
  assigned: boolean;
}

export interface VoiceOption {
  id: string;
  name: string;
  language: string | null;
  description: string | null;
}

export interface VoicesResponse {
  provider: string;
  default: string | null;
  items: VoiceOption[];
}

/** Agent voice settings (``AgentConfig.voice``). */
export interface AgentVoiceConfig {
  enabled: boolean;
  voice: string;
  language: string;
  greeting: string;
}

/** Frames sent by the voice service on a browser session. */
export type ServerFrame =
  | ({ type: "session_started"; mode: VoiceMode; call_id: string; conversation_id: string | null; recording: boolean } & Record<string, unknown>)
  | { type: "transcript_partial"; text: string }
  | { type: "transcript_committed"; text: string; replace?: boolean }
  | { type: "agent_text_delta"; text: string }
  | { type: "agent_text_done"; text: string; run_id: string | null }
  | { type: "agent_status"; text: string }
  | { type: "filler"; text: string }
  | { type: "agent_approval"; run_id: string; approval_id: string; prompt?: string | null }
  | { type: "agent_interaction"; run_id: string; interaction_id: string; kind: string }
  | { type: "audio"; data: string }
  | { type: "speak"; segment: number; text: string; duration_ms: number }
  | { type: "metrics"; metrics: TurnMetrics }
  | { type: "interrupted"; heard_text: string | null }
  | { type: "error"; message: string; code?: string }
  | { type: "session_transcript"; entries: TranscriptEntry[] }
  | { type: "session_ended" }
  | {
      type: "call_summary";
      call_id: string;
      conversation_id: string | null;
      status: string;
      duration_ms: number | null;
      voice_cost_usd: string;
      model_cost_usd: string;
      turns: number;
      recording: boolean;
    };

export type CallSummaryFrame = Extract<ServerFrame, { type: "call_summary" }>;

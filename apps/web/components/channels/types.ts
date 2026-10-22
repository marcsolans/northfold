/** Types of the channels and conversations API (`/api/v1/channels`, `/api/v1/conversations`). */

export const CHANNEL_PROVIDERS = ["whatsapp", "slack", "teams", "telegram", "email"] as const;
export type ChannelProvider = (typeof CHANNEL_PROVIDERS)[number];
export type ChannelStatus = "active" | "demo" | "error" | "disabled";
export type ChannelEnvironment = "production" | "development";

export function isChannelProvider(value: string): value is ChannelProvider {
  return (CHANNEL_PROVIDERS as readonly string[]).includes(value);
}

export interface ChannelStats {
  conversations: number;
  messages_24h: number;
  failed_24h: number;
  last_message_at: string | null;
}

export interface Channel {
  id: string;
  project_id: string;
  provider: string;
  name: string;
  workforce_id: string;
  workforce_name: string | null;
  status: ChannelStatus;
  demo: boolean;
  environment: ChannelEnvironment;
  development_fallback: boolean;
  error: string | null;
  config: Record<string, unknown>;
  credentials_set: string[];
  credential_source: "channel" | "platform" | "mixed" | "none";
  missing_credentials: string[];
  webhook_url: string;
  inbound_address: string | null;
  supported: boolean;
  stats: ChannelStats;
  created_at: string;
  updated_at: string;
}

export interface ChannelCreated extends Channel {
  webhook_secret: string;
}

export interface CredentialFieldInfo {
  key: string;
  required: boolean;
  secret: boolean;
  platform_available: boolean;
}

export interface ProviderInfo {
  provider: ChannelProvider;
  label: string;
  max_text: number;
  credential_fields: CredentialFieldInfo[];
  config_keys: string[];
  required_config: CredentialFieldInfo[];
  platform_ready: boolean;
}

export interface ChannelTest {
  ok: boolean;
  status: ChannelStatus;
  demo: boolean;
  details: Record<string, unknown>;
  error: string | null;
  checked_at: string;
}

export interface SecretRotated {
  webhook_secret: string;
  webhook_url: string;
}

export interface SimulateResult {
  message_id: string;
  conversation_id: string;
  sender: string;
  duplicate: boolean;
}

export interface ChannelMessage {
  id: string;
  conversation_id: string | null;
  direction: "inbound" | "outbound";
  kind: string;
  status: string;
  sender_id: string | null;
  sender_name: string | null;
  text: string;
  error: string | null;
  error_code: string | null;
  run_id: string | null;
  simulated: boolean;
  parts: number | null;
  created_at: string;
  processed_at: string | null;
}

export interface ChannelMessagePage {
  items: ChannelMessage[];
  next_cursor: string | null;
}

export interface ConversationItem {
  id: string;
  provider: string;
  channel_id: string | null;
  channel_name: string | null;
  workforce_name: string;
  contact_id: string;
  contact_name: string | null;
  title: string;
  status: "open" | "closed";
  message_count: number;
  last_message: { role: string; text: string; at: string | null } | null;
  last_run_id: string | null;
  pending_approvals: number;
  failed_deliveries: number;
  simulated: boolean;
  created_at: string;
  updated_at: string;
}

export interface ConversationPage {
  items: ConversationItem[];
  next_cursor: string | null;
  providers: { provider: string; count: number }[];
}

export interface Delivery {
  status: string;
  kind: string;
  error: string | null;
  error_code: string | null;
  parts: number | null;
}

export interface ThreadMessage {
  index: number;
  role: "user" | "assistant";
  text: string;
  at: string | null;
  run_id: string | null;
  notice: "approval_pending" | "error" | null;
  attachments: string[];
  error: { code?: string | null; message?: string | null } | null;
  delivery: Delivery | null;
}

export interface ConversationDetail {
  id: string;
  project_id: string;
  provider: string;
  channel: { id: string; name: string; provider: string; demo: boolean; status: ChannelStatus } | null;
  workforce_name: string;
  contact_id: string;
  contact_name: string | null;
  title: string;
  status: "open" | "closed";
  simulated: boolean;
  external_thread_id: string | null;
  last_run_id: string | null;
  messages: ThreadMessage[];
  pending_approvals: { id: string; title: string; tool_name: string; created_at: string }[];
  created_at: string;
  updated_at: string;
}

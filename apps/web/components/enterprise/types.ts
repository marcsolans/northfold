import type { Role } from "@/lib/types";

export type AssignableRole = Exclude<Role, "owner">;
export const ASSIGNABLE_ROLES: AssignableRole[] = ["admin", "builder", "viewer"];
export type SsoType = "oidc" | "saml";
export type PresetKey = "entra" | "google" | "okta" | "generic";
export const PRESET_KEYS: PresetKey[] = ["entra", "google", "okta", "generic"];

export interface SsoOverview {
  sso_available: boolean;
  scim_available: boolean;
  sso_upgrade_to: string | null;
  scim_upgrade_to: string | null;
  oidc_redirect_uri: string;
  scim_base_url: string;
}

export interface CertificateInfo {
  pem: string;
  subject: string;
  not_after: string;
  expired: boolean;
  fingerprint_sha256: string;
}

export interface SsoConnection {
  id: string;
  type: SsoType;
  name: string;
  domain: string;
  domain_verified: boolean;
  default_role: AssignableRole;
  enforce: boolean;
  enabled: boolean;
  config: Record<string, unknown> & { preset?: PresetKey; jit_provisioning?: boolean; certificates?: CertificateInfo[] };
  service_provider: Record<string, string>;
  login_url: string;
  mappings: number;
  created_at: string;
  updated_at: string;
}

export interface SsoPresets {
  presets: Record<PresetKey, { label: string; placeholders: string[]; oidc: Record<string, unknown>; saml: Record<string, unknown> }>;
  name_id_formats: string[];
}

export interface GroupMapping {
  id: string;
  connection_id: string;
  external_group: string;
  role: AssignableRole;
}

export interface OrgDomain {
  id: string;
  domain: string;
  verified_at: string | null;
  verification_method: string | null;
  last_checked_at: string | null;
  record: { type: string; name: string; value: string };
  created_at: string;
}

export interface ScimToken {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ScimUser {
  user_id: string;
  email: string;
  user_name: string | null;
  active: boolean;
  external_id: string | null;
  updated_at: string;
}

export interface SsoTestResult {
  ok: boolean;
  problems: { code: string; message: string }[];
  identity: { subject: string; email: string; name: string | null; groups: string[]; mfa: boolean } | null;
  user_exists?: boolean;
  member?: boolean;
  role?: string;
  matched_groups?: string[];
  connection_id: string;
  at: string;
}

export interface Person {
  id: string;
  email: string | null;
  name: string | null;
}

export interface PostCheck {
  check: string;
  sql: string;
  remaining: number;
}

export interface DataRequest {
  id: string;
  org_id: string | null;
  org_name: string | null;
  kind: "export" | "delete";
  scope: "user" | "org";
  reach: "org" | "account";
  status: "pending" | "running" | "completed" | "failed" | "expired";
  requester: Person | null;
  subject: Person | null;
  created_at: string;
  completed_at: string | null;
  file_ready: boolean;
  expires_at: string | null;
  verified: boolean | null;
  error: { code: string; message: string } | null;
  report: {
    deletion?: {
      verified?: boolean;
      deleted?: Record<string, number>;
      anonymized?: Record<string, number>;
      post_checks?: PostCheck[];
      account_erased?: boolean;
    };
    export?: { bytes?: number; files?: number; tables?: Record<string, number> };
  } & Record<string, unknown>;
}

export interface ResidencyOverview {
  data_residency: "standard" | "eu_strict";
  region: string;
  regions: { id: string; name: string }[];
  model_route: "anthropic" | "bedrock";
  eu_strict_available: boolean;
  eu_strict_upgrade_to: string | null;
  bedrock: { configured: boolean; region: string; allowed_regions: string[]; models: { model: string; bedrock_id: string }[] };
  providers: { kind: "model" | "embeddings" | "email" | "voice"; provider: string; region: string | null; allowed_in_eu_strict: boolean; active: boolean }[];
  retention: { trace_days: number; conversation_days: number; last_purge_at: string | null; last_purge: Record<string, unknown> | null };
}

export interface SystemStatus {
  environment: string;
  bedrock_available: boolean;
  pending_keys: { variable: string; feature: string }[];
}

export interface Member {
  user_id: string;
  email: string;
  name: string | null;
  role: Role;
  source: string;
}

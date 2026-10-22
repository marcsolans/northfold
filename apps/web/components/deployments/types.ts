/** Types mirroring the deployments API (`routers/deployments.py`, environments and project versions). */

import type { StatusTone } from "@messer/ui";

export type EnvironmentName = "development" | "production";
export const ENVIRONMENTS: readonly EnvironmentName[] = ["development", "production"];

export function isEnvironmentName(value: string): value is EnvironmentName {
  return value === "development" || value === "production";
}

export type DeploymentStatus = "pending" | "evaluating" | "deploying" | "live" | "failed" | "superseded" | "rolled_back";
export const ACTIVE_STATUSES: readonly string[] = ["pending", "evaluating", "deploying"];
export const DEPLOYMENT_STATUSES: readonly DeploymentStatus[] = [
  "pending",
  "evaluating",
  "deploying",
  "live",
  "failed",
  "superseded",
  "rolled_back",
];

export function isActive(status: string): boolean {
  return ACTIVE_STATUSES.includes(status);
}

export const STATUS_TONE: Record<DeploymentStatus, StatusTone> = {
  pending: "info",
  evaluating: "info",
  deploying: "info",
  live: "success",
  failed: "danger",
  superseded: "neutral",
  rolled_back: "neutral",
};

export function statusTone(status: string): StatusTone {
  return STATUS_TONE[status as DeploymentStatus] ?? "neutral";
}

export type LogLevel = "info" | "warning" | "error";

/** One pipeline step; gate entries carry `member` (and `passed`/`failed` when the member has evals). */
export interface DeploymentLog {
  at: string;
  level: LogLevel | string;
  message: string;
  member?: string;
  passed?: number;
  failed?: number;
  force?: boolean;
  skip_evals?: boolean;
  [key: string]: unknown;
}

export interface Deployment {
  id: string;
  environment: EnvironmentName | string;
  version_id: string;
  version: number | null;
  git_commit: string | null;
  message: string | null;
  status: DeploymentStatus | string;
  logs: DeploymentLog[];
  eval_run_id: string | null;
  forced: boolean;
  created_by: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface DnsRecord {
  type: "CNAME" | "TXT" | string;
  name: string;
  value: string;
}

export type DomainStatus = "pending" | "verified" | "active" | "failed";

export interface DomainView {
  environment: string;
  domain: string | null;
  status: DomainStatus | null;
  dns: DnsRecord[];
  url: string | null;
  /** Only in the answer of `POST …/domain/verify`. */
  checks?: { txt: boolean; cname: boolean };
}

/** Organization member (`GET /members`), used to show who published. */
export interface OrgMember {
  user_id: string;
  email: string;
  name: string | null;
}

/** Same rule as the API (`routers/deployments.py`). */
export const DOMAIN_PATTERN = /^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;

export interface GateResult {
  member: string;
  /** `null` when the member has no evals. */
  passed: number | null;
  failed: number | null;
}

/** Gate results per member, read from the structured pipeline logs. */
export function gateResults(logs: DeploymentLog[]): GateResult[] {
  const results: GateResult[] = [];
  for (const entry of logs) {
    if (typeof entry.member !== "string") continue;
    const hasCounts = typeof entry.passed === "number" || typeof entry.failed === "number";
    results.push({
      member: entry.member,
      passed: hasCounts ? Number(entry.passed ?? 0) : null,
      failed: hasCounts ? Number(entry.failed ?? 0) : null,
    });
  }
  return results;
}

/** Rollbacks re-deploy a version that already passed its gate, so the evals are skipped. */
export function evalsSkipped(logs: DeploymentLog[]): boolean {
  return logs.some((entry) => entry.skip_evals === true);
}

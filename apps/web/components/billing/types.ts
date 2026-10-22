/** Types of the billing, credits and budgets API (apps/api routers billing.py, plans.py, budgets.py). */

export type Interval = "month" | "year";
export type BillingMode = "stripe" | "simulated";

export const LIMIT_KEYS = ["seats", "projects", "runs_month", "credits_month", "storage_gb"] as const;
export type LimitKey = (typeof LIMIT_KEYS)[number];

export const FEATURE_KEYS = [
  "public_chat",
  "api",
  "connectors",
  "channels",
  "deployments",
  "voice",
  "sso",
  "audit",
  "guard",
  "priority_support",
  "eu_strict",
  "byoc",
  "scim",
  "sla",
  "dedicated_engineer",
] as const;
export type FeatureKey = (typeof FEATURE_KEYS)[number];

export interface PlanLimits {
  seats: number;
  projects: number;
  runs_month: number;
  credits_month: number;
  storage_gb: number;
  features: string[];
}

export interface Plan {
  id: string;
  name: string;
  description: string;
  price_month_eur: string;
  price_year_eur: string;
  price_is_starting: boolean;
  self_serve: boolean;
  sort_order: number;
  limits: PlanLimits;
}

export interface CreditPack {
  id: string;
  credits: number;
  price_eur: string;
}

export type SubscriptionStatus = "trialing" | "active" | "past_due" | "canceled" | "incomplete";
export type SubscriptionState = SubscriptionStatus | "trial_expired" | "none";

export interface SubscriptionView {
  status: SubscriptionStatus;
  state: SubscriptionState;
  plan_id: string;
  interval: Interval;
  trial_ends_at: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  canceled_at: string | null;
  past_due_since: string | null;
  grace_ends_at: string | null;
  read_only: boolean;
  paid: boolean;
  has_customer: boolean;
  test_mode: boolean;
}

export interface LimitUsage {
  used: number;
  limit: number;
}

export interface Usage {
  period_start: string;
  period_end: string;
  seats: LimitUsage;
  projects: LimitUsage;
  runs_month: LimitUsage;
  credits: { used: string; limit: number; balance: string };
  storage_gb: { used: number; used_bytes: number; limit: number };
}

export interface BillingOverview {
  mode: BillingMode;
  test_mode: boolean;
  publishable_key: string | null;
  plan: Plan | null;
  subscription: SubscriptionView | null;
  usage: Usage;
  can_manage: boolean;
}

export interface CheckoutAction {
  action: "checkout" | "updated";
  url: string | null;
  checkout_id: string | null;
}

export interface Invoice {
  id: string;
  stripe_invoice_id: string;
  number: string | null;
  status: string;
  amount_due_eur: string;
  amount_paid_eur: string;
  tax_eur: string;
  hosted_invoice_url: string | null;
  pdf_url: string | null;
  period_start: string | null;
  period_end: string | null;
  created_at: string;
  test: boolean;
}

export interface AutoTopup {
  enabled: boolean;
  threshold: number;
  pack_id: string | null;
  last_status: "pending" | "succeeded" | "failed" | null;
  last_error: string | null;
  last_requested_at: string | null;
}

export interface CreditsOverview {
  balance: string;
  credits_month: number;
  used_this_month: string;
  added_this_month: string;
  period_start: string;
  period_end: string;
  credit_usd: string;
  mode: BillingMode;
  test_mode: boolean;
  can_auto_topup: boolean;
  auto_topup: AutoTopup;
  packs: CreditPack[];
}

export type LedgerKind = "grant" | "usage" | "purchase" | "adjustment";

export interface LedgerEntry {
  id: string;
  kind: LedgerKind;
  amount: string;
  note: string | null;
  run_id: string | null;
  project_id: string | null;
  project_name: string | null;
  cost_usd: string | null;
  created_at: string;
  created_by_email: string | null;
}

export interface LedgerPage {
  items: LedgerEntry[];
  total: number;
}

export interface SimulatedCheckout {
  id: string;
  kind: "subscription" | "credit_pack";
  status: "open" | "completed" | "canceled" | "expired";
  amount_eur: string;
  plan: Plan | null;
  interval: Interval | null;
  pack: CreditPack | null;
  org_name: string;
  expires_at: string;
  created_at: string;
  current_plan_id: string | null;
  mode: BillingMode;
}

export interface CheckoutResult {
  status: string;
  kind: string;
  redirect: string;
}

export type BudgetPeriod = "day" | "week" | "month";

export interface Budget {
  id: string;
  project_id: string | null;
  project_name: string | null;
  period: BudgetPeriod;
  limit_usd: string;
  alert_threshold_pct: number;
  hard_stop: boolean;
  spent_usd: string;
  remaining_usd: string;
  pct: number;
  state: "ok" | "alert" | "exceeded";
  period_start: string;
  period_end: string;
  last_alerted_at: string | null;
  created_at: string;
  updated_at: string;
}

export const UNLIMITED = -1;

export function isUnlimited(value: number): boolean {
  return value === UNLIMITED;
}

/** Annual discount versus paying 12 monthly prices, in whole percent (0 when there is none). */
export function annualDiscountPct(plan: Pick<Plan, "price_month_eur" | "price_year_eur">): number {
  const monthly = Number(plan.price_month_eur) * 12;
  const yearly = Number(plan.price_year_eur);
  if (monthly <= 0 || yearly >= monthly) return 0;
  return Math.round((1 - yearly / monthly) * 100);
}

export function monthlyEquivalent(plan: Pick<Plan, "price_month_eur" | "price_year_eur">, interval: Interval): number {
  return interval === "year" ? Number(plan.price_year_eur) / 12 : Number(plan.price_month_eur);
}

export const PLANS_KEY = ["plans"] as const;
export const BILLING_KEY = ["billing"] as const;
export const CREDITS_KEY = ["billing", "credits"] as const;

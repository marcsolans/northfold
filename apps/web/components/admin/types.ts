/** Types of the backoffice API (apps/api routers admin.py and admin_catalog.py). */

import type { Invoice, LedgerEntry, Plan, PlanLimits, SubscriptionView, Usage } from "@/components/billing/types";

export interface OrgRow {
  id: string;
  name: string;
  slug: string;
  status: "active" | "blocked";
  blocked_reason: string | null;
  created_at: string;
  owner_email: string | null;
  plan_id: string | null;
  plan_name: string | null;
  subscription_status: string;
  interval: "month" | "year" | null;
  trial_ends_at: string | null;
  test_mode: boolean;
  mrr_eur: string;
  members: number;
  projects: number;
  runs_month: number;
  credits_used_month: string;
  credits_balance: string;
  model_cost_usd_month: string;
  credits_revenue_usd_month: string;
  margin_usd_month: string;
  last_active_at: string | null;
}

export interface OrgPage {
  items: OrgRow[];
  total: number;
}

export interface AdminMember {
  user_id: string;
  email: string;
  name: string | null;
  role: string;
  status: string;
  is_superadmin: boolean;
  last_login_at: string | null;
  joined_at: string;
}

export interface AdminProject {
  id: string;
  name: string;
  created_at: string;
  archived_at: string | null;
  template_id: string | null;
  runs_month: number;
  cost_usd_month: string;
}

export interface AdminAudit {
  id: string;
  created_at: string;
  org_id: string | null;
  action: string;
  actor_email: string | null;
  impersonated_by_email: string | null;
  entity_type: string | null;
  entity_id: string | null;
  diff: Record<string, unknown>;
  ip: string | null;
}

export interface OrgDetail {
  org: OrgRow;
  region: string;
  data_residency: string;
  plan: Plan | null;
  subscription: SubscriptionView | null;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  usage: Usage;
  members: AdminMember[];
  projects: AdminProject[];
  ledger: LedgerEntry[];
  invoices: Invoice[];
  audit: AdminAudit[];
}

export interface AdminUser {
  id: string;
  email: string;
  name: string | null;
  status: "active" | "blocked";
  is_superadmin: boolean;
  last_login_at: string | null;
  created_at: string;
  orgs: { id: string; name: string; role: string }[];
}

export interface UserPage {
  items: AdminUser[];
  total: number;
}

export interface MonthPoint {
  month: string;
  ai_cost_usd: string;
  credits_used: string;
  credits_revenue_usd: string;
  margin_usd: string;
  billed_revenue_eur: string;
}

export interface BusinessMetrics {
  test_mode: boolean;
  generated_at: string;
  mrr_eur: string;
  arr_eur: string;
  paid_subscriptions: number;
  trials_active: number;
  past_due: number;
  mrr_by_plan: { plan_id: string; plan_name: string; subscriptions: number; mrr_eur: string }[];
  signups: { week_start: string; users: number; orgs: number }[];
  trial_conversion: {
    window_days: number;
    trials_started: number;
    converted: number;
    expired_unconverted: number;
    rate: number | null;
  };
  churn: { window_days: number; canceled: number; base: number; rate: number | null };
  ai_cost_vs_revenue: MonthPoint[];
  current_month: MonthPoint | null;
  activation_funnel: { step: "signed_up" | "project" | "data" | "test" | "deploy" | "paid"; orgs: number }[];
  totals: { orgs: number; users: number };
}

export interface StripeSync {
  mode: string;
  ok: boolean;
  changed: boolean;
  error: string | null;
}

export interface AdminPlan extends Plan {
  public: boolean;
  stripe_product_id: string | null;
  stripe_price_ids: Record<string, string>;
  subscriptions: number;
  updated_at: string;
  stripe_sync: StripeSync | null;
}

export type { PlanLimits };

export interface ModelPrice {
  model: string;
  provider: string;
  display_name: string;
  input_per_mtok_usd: string;
  output_per_mtok_usd: string;
  cache_read_per_mtok_usd: string;
  cache_write_per_mtok_usd: string;
  context_window: number | null;
  active: boolean;
  updated_at: string;
}

export interface AdminTemplate {
  id: string;
  sector: string;
  name: string;
  name_en: string;
  description: string;
  public: boolean;
  sort_order: number;
  tags: unknown[];
  updated_at: string;
}

export interface FeatureFlag {
  key: string;
  description: string;
  enabled: boolean;
  targeting: { plans: string[]; orgs: string[] };
  updated_at: string;
}

export const ADMIN_KEY = ["admin"] as const;

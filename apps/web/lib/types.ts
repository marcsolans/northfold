export type Role = "owner" | "admin" | "builder" | "viewer";

export interface OrgSummary {
  id: string;
  name: string;
  slug: string;
  role: Role | null;
  data_residency: "standard" | "eu_strict";
  region: string;
  plan_id: string | null;
}

export interface BillingState {
  status: string;
  plan_id: string | null;
  read_only: boolean;
  blocked: boolean;
  trial_ends_at: string | null;
  grace_ends_at: string | null;
}

export interface Me {
  id: string;
  email: string;
  name: string | null;
  avatar: string | null;
  locale: "es" | "en";
  is_superadmin: boolean;
  impersonated_by: string | null;
  mfa_enabled: boolean;
  email_verified: boolean;
  active_org: OrgSummary | null;
  orgs: OrgSummary[];
  billing: BillingState | null;
}

export const ROLE_RANK: Record<Role, number> = { viewer: 1, builder: 2, admin: 3, owner: 4 };

export function hasRole(me: Me | undefined, min: Role): boolean {
  if (!me) return false;
  if (me.is_superadmin) return true;
  const role = me.active_org?.role;
  return role ? ROLE_RANK[role] >= ROLE_RANK[min] : false;
}

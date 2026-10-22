export type SettingsSection =
  | "profile"
  | "organization"
  | "members"
  | "sso"
  | "billing"
  | "credits"
  | "budgets"
  | "apiKeys"
  | "models"
  | "residency"
  | "audit"
  | "data"
  | "modelPolicy";

export const SETTINGS_GROUPS: { group: "account" | "org" | "governance" | "developers"; items: { key: SettingsSection; href: string }[] }[] = [
  { group: "account", items: [{ key: "profile", href: "/app/settings/profile" }] },
  {
    group: "org",
    items: [
      { key: "organization", href: "/app/settings/organization" },
      { key: "members", href: "/app/settings/members" },
      { key: "sso", href: "/app/settings/sso" },
      { key: "billing", href: "/app/settings/billing" },
      { key: "credits", href: "/app/settings/credits" },
    ],
  },
  {
    group: "governance",
    items: [
      { key: "budgets", href: "/app/settings/budgets" },
      { key: "models", href: "/app/settings/models" },
      { key: "residency", href: "/app/settings/residency" },
      { key: "audit", href: "/app/settings/audit" },
      { key: "data", href: "/app/settings/data" },
      { key: "modelPolicy", href: "/app/settings/model-policy" },
    ],
  },
  {
    group: "developers",
    items: [
      { key: "apiKeys", href: "/app/settings/api-keys" },
    ],
  },
];

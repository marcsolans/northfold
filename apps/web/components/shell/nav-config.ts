import {
  BarChart3,
  BookOpen,
  CheckSquare,
  FolderKanban,
  Home,
  LayoutTemplate,
  type LucideIcon,
  Plug,
  Settings,
} from "lucide-react";

export interface NavItem {
  key: "home" | "projects" | "approvals" | "knowledge" | "connectors" | "templates" | "analytics" | "settings";
  href: string;
  icon: LucideIcon;
}

export const MAIN_NAV: NavItem[] = [
  { key: "home", href: "/app", icon: Home },
  { key: "projects", href: "/app/projects", icon: FolderKanban },
  { key: "approvals", href: "/app/approvals", icon: CheckSquare },
  { key: "knowledge", href: "/app/knowledge", icon: BookOpen },
  { key: "connectors", href: "/app/connectors", icon: Plug },
  { key: "templates", href: "/app/templates", icon: LayoutTemplate },
  { key: "analytics", href: "/app/analytics", icon: BarChart3 },
  { key: "settings", href: "/app/settings", icon: Settings },
];

export const PROJECT_NAV = [
  "overview",
  "agents",
  "workflows",
  "knowledge",
  "interfaces",
  "channels",
  "conversations",
  "traces",
  "analytics",
  "deployments",
  "settings",
] as const;

export type ProjectNavKey = (typeof PROJECT_NAV)[number];

export function projectHref(projectId: string, key: ProjectNavKey): string {
  return key === "overview" ? `/app/projects/${projectId}` : `/app/projects/${projectId}/${key}`;
}

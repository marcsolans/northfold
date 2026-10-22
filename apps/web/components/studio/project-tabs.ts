import { PROJECT_NAV, type ProjectNavKey } from "@/components/shell/nav-config";

/**
 * Project tabs whose pages exist. Other areas add their key here when their page under
 * `app/app/projects/[id]/<key>/` ships; the tab bar renders them in PROJECT_NAV order.
 */
export const ENABLED_PROJECT_TABS: readonly ProjectNavKey[] = ["overview", "agents", "traces", "settings", "analytics", "interfaces", "workflows", "deployments", "channels", "conversations"];

export function enabledProjectTabs(): ProjectNavKey[] {
  return PROJECT_NAV.filter((key) => ENABLED_PROJECT_TABS.includes(key));
}

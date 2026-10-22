"use client";

import { cn } from "@messer/ui";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

const ITEMS = [
  { key: "overview", href: "/app/analytics" },
  { key: "alarms", href: "/app/analytics/alarms" },
  { key: "metrics", href: "/app/analytics/metrics" },
] as const;

/** Sub-navigation of the organization analytics area. The overview keeps its filters in the URL. */
export function AnalyticsNav() {
  const t = useTranslations("analytics.nav");
  const pathname = usePathname();
  const params = useSearchParams();
  return (
    <nav className="-mb-px flex gap-1 overflow-x-auto border-b border-border" aria-label={t("label")}>
      {ITEMS.map((item) => {
        const active = item.key === "overview" ? pathname === item.href : pathname.startsWith(item.href);
        const href = item.key === "overview" && pathname === item.href && params.toString() ? `${item.href}?${params.toString()}` : item.href;
        return (
          <Link
            key={item.key}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "whitespace-nowrap border-b-2 px-3 py-2 text-sm text-fg-muted hover:text-fg",
              active ? "border-accent font-medium text-fg" : "border-transparent",
            )}
          >
            {t(item.key)}
          </Link>
        );
      })}
    </nav>
  );
}

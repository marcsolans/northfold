"use client";

import { Badge, Button, EmptyState, Logo, SkeletonRows, cn } from "@messer/ui";
import {
  Building2,
  ClipboardList,
  Cpu,
  Flag,
  LayoutTemplate,
  LineChart,
  type LucideIcon,
  ShieldAlert,
  Tag,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useMe } from "@/lib/hooks/use-me";

interface AdminNavItem {
  key: "metrics" | "orgs" | "users" | "plans" | "modelPrices" | "templates" | "flags" | "audit";
  href: string;
  icon: LucideIcon;
}

export const ADMIN_NAV: AdminNavItem[] = [
  { key: "metrics", href: "/admin", icon: LineChart },
  { key: "orgs", href: "/admin/orgs", icon: Building2 },
  { key: "users", href: "/admin/users", icon: Users },
  { key: "plans", href: "/admin/plans", icon: Tag },
  { key: "modelPrices", href: "/admin/model-prices", icon: Cpu },
  { key: "templates", href: "/admin/templates", icon: LayoutTemplate },
  { key: "flags", href: "/admin/flags", icon: Flag },
  { key: "audit", href: "/admin/audit", icon: ClipboardList },
];

/** Backoffice layout: its own sidebar, superadmins only (the API enforces it too). */
export function AdminShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations("admin");
  const pathname = usePathname();
  const router = useRouter();
  const me = useMe();

  React.useEffect(() => {
    if (me.error && "status" in me.error && (me.error as { status: number }).status === 401) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [me.error, pathname, router]);

  if (me.isLoading || (!me.data && !me.error)) {
    return (
      <div className="flex min-h-screen">
        <aside className="hidden w-56 border-r border-border bg-subtle p-3 md:block">
          <SkeletonRows rows={8} />
        </aside>
        <main className="flex-1 p-8">
          <SkeletonRows rows={6} />
        </main>
      </div>
    );
  }
  if (!me.data?.is_superadmin) {
    return (
      <div className="mx-auto flex min-h-screen max-w-lg items-center px-4">
        <EmptyState
          icon={<ShieldAlert />}
          title={t("shell.forbiddenTitle")}
          description={me.data?.impersonated_by ? t("shell.forbiddenImpersonating") : t("shell.forbidden")}
          action={
            <Button asChild variant="dark">
              <Link href="/app">{t("shell.backToApp")}</Link>
            </Button>
          }
        />
      </div>
    );
  }
  const isActive = (href: string) => (href === "/admin" ? pathname === "/admin" : pathname.startsWith(href));
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-border bg-subtle md:flex">
        <div className="flex h-12 items-center gap-2 px-4">
          <Link href="/admin" aria-label="Messer">
            <Logo />
          </Link>
          <Badge tone="accent">{t("shell.badge")}</Badge>
        </div>
        <nav className="mt-2 flex flex-1 flex-col gap-0.5 px-2" aria-label={t("shell.nav")}>
          {ADMIN_NAV.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              aria-current={isActive(item.href) ? "page" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-fg-muted hover:bg-muted hover:text-fg [&_svg]:size-4",
                isActive(item.href) && "bg-surface font-medium text-fg shadow-[0_0_0_1px_var(--border)]",
              )}
            >
              <item.icon />
              {t(`nav.${item.key}`)}
            </Link>
          ))}
        </nav>
        <div className="border-t border-border p-2">
          <Link href="/app" className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-fg-muted hover:bg-muted hover:text-fg">
            {t("shell.backToApp")}
          </Link>
          <p className="truncate px-2 pt-1 text-xs text-fg-subtle">{me.data.email}</p>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <nav className="flex gap-1 overflow-x-auto border-b border-border px-2 py-1 md:hidden" aria-label={t("shell.nav")}>
          {ADMIN_NAV.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              className={cn(
                "whitespace-nowrap rounded-md px-2 py-1 text-sm text-fg-muted",
                isActive(item.href) && "bg-muted font-medium text-fg",
              )}
            >
              {t(`nav.${item.key}`)}
            </Link>
          ))}
        </nav>
        <main className="mx-auto w-full max-w-7xl min-w-0 flex-1 px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}

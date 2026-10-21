"use client";

import {
  Alert,
  Avatar,
  Button,
  CommandPalette,
  type CommandItem,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Kbd,
  Logo,
  SkeletonRows,
  cn,
} from "@messer/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronsUpDown, LogOut, Monitor, Moon, Plus, Search, Shield, Sun, User } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import * as React from "react";

import { http } from "@/lib/api";
import { useMe } from "@/lib/hooks/use-me";
import type { Me } from "@/lib/types";

import { MAIN_NAV } from "./nav-config";
import { NotificationsBell } from "./notifications-bell";

function useCommandShortcut(onOpen: () => void) {
  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpen();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onOpen]);
}

function OrgSwitcher({ me }: { me: Me }) {
  const t = useTranslations("nav");
  const qc = useQueryClient();
  const router = useRouter();
  const switchTo = async (orgId: string) => {
    await http.post(`/orgs/${orgId}/switch`);
    await qc.invalidateQueries();
    router.push("/app");
  };
  const createOrg = async () => {
    const name = window.prompt(t("orgNamePrompt"));
    if (!name?.trim()) return;
    await http.post("/orgs", { name: name.trim() });
    await qc.invalidateQueries();
    router.push("/onboarding");
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
          aria-label={t("switchOrg")}
        >
          <span className="flex size-5 items-center justify-center rounded-sm bg-fg text-[11px] font-semibold text-bg">
            {(me.active_org?.name ?? "?").slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1 truncate font-medium">{me.active_org?.name ?? "—"}</span>
          <ChevronsUpDown className="size-3.5 text-fg-subtle" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-60">
        <DropdownMenuLabel>{t("switchOrg")}</DropdownMenuLabel>
        {me.orgs.map((org) => (
          <DropdownMenuItem key={org.id} onSelect={() => void switchTo(org.id)}>
            <span className="min-w-0 flex-1 truncate">{org.name}</span>
            {org.id === me.active_org?.id ? <Check /> : null}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void createOrg()}>
          <Plus />
          {t("createOrg")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu({ me }: { me: Me }) {
  const t = useTranslations("nav");
  const { setTheme, theme } = useTheme();
  const locale = useLocale();
  const router = useRouter();
  const setLocale = (value: "es" | "en") => {
    document.cookie = `NEXT_LOCALE=${value}; Path=/; Max-Age=31536000; SameSite=Lax`;
    void http.patch("/me", { locale: value }).catch(() => undefined);
    router.refresh();
  };
  const logout = async () => {
    await http.post("/auth/logout");
    window.location.href = "/login";
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" className="rounded-full" aria-label={me.email}>
          <Avatar name={me.name ?? me.email} src={me.avatar} />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-64">
        <DropdownMenuLabel>
          <span className="block truncate text-sm font-medium text-fg">{me.name ?? me.email}</span>
          <span className="block truncate">{me.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/app/settings/profile">
            <User />
            {t("profile")}
          </Link>
        </DropdownMenuItem>
        {me.is_superadmin ? (
          <DropdownMenuItem asChild>
            <Link href="/admin">
              <Shield />
              {t("admin")}
            </Link>
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t("theme")}</DropdownMenuLabel>
        <div className="flex gap-1 px-2 pb-1">
          {(
            [
              ["light", Sun, t("themeLight")],
              ["dark", Moon, t("themeDark")],
              ["system", Monitor, t("themeSystem")],
            ] as const
          ).map(([value, Icon, label]) => (
            <Button
              key={value}
              size="icon-sm"
              variant={theme === value ? "secondary" : "ghost"}
              aria-label={label}
              onClick={() => setTheme(value)}
            >
              <Icon />
            </Button>
          ))}
        </div>
        <DropdownMenuLabel>{t("language")}</DropdownMenuLabel>
        <div className="flex gap-1 px-2 pb-1">
          {(["es", "en"] as const).map((value) => (
            <Button key={value} size="sm" variant={locale === value ? "secondary" : "ghost"} onClick={() => setLocale(value)}>
              {value.toUpperCase()}
            </Button>
          ))}
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()}>
          <LogOut />
          {t("logout")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Banners({ me }: { me: Me }) {
  const t = useTranslations("nav");
  const locale = useLocale();
  const banners: React.ReactNode[] = [];
  if (me.impersonated_by) {
    banners.push(
      <Alert
        key="imp"
        tone="accent"
        className="rounded-none border-x-0 border-t-0"
        action={
          <Button
            size="sm"
            variant="dark"
            onClick={async () => {
              await http.post("/admin/impersonation/stop");
              window.location.href = "/admin";
            }}
          >
            {t("stopImpersonating")}
          </Button>
        }
      >
        {t("impersonating", { email: me.email })}
      </Alert>,
    );
  }
  const billing = me.billing;
  if (billing?.blocked) {
    banners.push(
      <Alert key="blocked" tone="danger" className="rounded-none border-x-0 border-t-0">
        {t("blocked")}
      </Alert>,
    );
  } else if (billing) {
    const cta = (
      <Button asChild size="sm" variant="dark">
        <Link href="/app/settings/billing">{t("choosePlan")}</Link>
      </Button>
    );
    if (billing.status === "trialing" && billing.trial_ends_at) {
      const days = Math.max(0, Math.ceil((new Date(billing.trial_ends_at).getTime() - Date.now()) / 86_400_000));
      banners.push(
        <Alert key="trial" tone="info" className="rounded-none border-x-0 border-t-0" action={cta}>
          {t("trialBanner", { days })}
        </Alert>,
      );
    } else if (billing.status === "trial_expired") {
      banners.push(
        <Alert key="trial-exp" tone="warning" className="rounded-none border-x-0 border-t-0" action={cta}>
          {t("trialExpired")}
        </Alert>,
      );
    } else if (billing.status === "past_due") {
      const date = billing.grace_ends_at ? new Date(billing.grace_ends_at).toLocaleDateString(locale) : "";
      banners.push(
        <Alert key="past-due" tone="warning" className="rounded-none border-x-0 border-t-0" action={cta}>
          {t("pastDue", { date })}
        </Alert>,
      );
    } else if (billing.status === "canceled") {
      banners.push(
        <Alert key="canceled" tone="warning" className="rounded-none border-x-0 border-t-0" action={cta}>
          {t("canceled")}
        </Alert>,
      );
    }
  }
  return <>{banners}</>;
}

interface ProjectLite {
  id: string;
  name: string;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations("nav");
  const pathname = usePathname();
  const router = useRouter();
  const me = useMe();
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const openPalette = React.useCallback(() => setPaletteOpen(true), []);
  useCommandShortcut(openPalette);

  const projects = useQuery({
    queryKey: ["projects", "palette"],
    queryFn: () => http.get<ProjectLite[]>("/projects"),
    enabled: paletteOpen && Boolean(me.data?.active_org),
  });

  React.useEffect(() => {
    if (me.error && "status" in me.error && (me.error as { status: number }).status === 401) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [me.error, pathname, router]);

  const items: CommandItem[] = React.useMemo(() => {
    const nav: CommandItem[] = MAIN_NAV.map((item) => ({
      id: `nav-${item.key}`,
      label: t(item.key),
      group: t("goTo"),
      icon: <item.icon />,
      onSelect: () => router.push(item.href),
    }));
    const actions: CommandItem[] = [
      { id: "new-composer", label: t("newComposer"), group: t("actionsGroup"), icon: <Plus />, onSelect: () => router.push("/app") },
      { id: "new-project", label: t("newProject"), group: t("actionsGroup"), icon: <Plus />, onSelect: () => router.push("/app/projects?new=1") },
    ];
    const projectItems: CommandItem[] = (projects.data ?? []).map((p) => ({
      id: `project-${p.id}`,
      label: p.name,
      group: t("projects"),
      onSelect: () => router.push(`/app/projects/${p.id}`),
    }));
    return [...actions, ...nav, ...projectItems];
  }, [projects.data, router, t]);

  if (me.isLoading || !me.data) {
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

  const isActive = (href: string) => (href === "/app" ? pathname === "/app" : pathname.startsWith(href));

  return (
    <div className="flex min-h-screen flex-col">
      <Banners me={me.data} />
      <div className="flex min-h-0 flex-1">
        <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-border bg-subtle md:flex">
          <div className="flex h-12 items-center px-4">
            <Link href="/app" aria-label="Messer">
              <Logo />
            </Link>
          </div>
          <div className="px-2">
            <OrgSwitcher me={me.data} />
          </div>
          <nav className="mt-3 flex flex-1 flex-col gap-0.5 px-2" aria-label="Principal">
            {MAIN_NAV.map((item) => (
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
                {t(item.key)}
              </Link>
            ))}
          </nav>
          <div className="border-t border-border p-2">
            <Link href="/docs" className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-fg-muted hover:bg-muted hover:text-fg">
              {t("docs")}
            </Link>
          </div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-12 items-center gap-3 border-b border-border bg-bg/95 px-4 backdrop-blur">
            <div className="md:hidden">
              <Logo compact />
            </div>
            <button
              type="button"
              onClick={openPalette}
              className="flex h-8 w-full max-w-sm items-center gap-2 rounded-md border border-border bg-surface px-2.5 text-sm text-fg-subtle hover:border-border-strong"
            >
              <Search className="size-4" />
              <span className="flex-1 text-left">{t("search")}</span>
              <Kbd>⌘K</Kbd>
            </button>
            <div className="ml-auto flex items-center gap-2">
              <NotificationsBell />
              <UserMenu me={me.data} />
            </div>
          </header>
          <nav className="flex gap-1 overflow-x-auto border-b border-border px-2 py-1 md:hidden" aria-label="Principal">
            {MAIN_NAV.map((item) => (
              <Link
                key={item.key}
                href={item.href}
                className={cn(
                  "whitespace-nowrap rounded-md px-2 py-1 text-sm text-fg-muted",
                  isActive(item.href) && "bg-muted font-medium text-fg",
                )}
              >
                {t(item.key)}
              </Link>
            ))}
          </nav>
          <main className="min-w-0 flex-1">{children}</main>
        </div>
      </div>
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        items={items}
        placeholder={t("searchPlaceholder")}
        emptyLabel={t("noResults")}
      />
    </div>
  );
}

"use client";

import { cn } from "@messer/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import type * as React from "react";

import { SETTINGS_GROUPS } from "@/components/settings/settings-nav";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const t = useTranslations("settings");
  const pathname = usePathname();
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 md:flex-row md:px-8">
      <aside className="md:w-52 md:shrink-0">
        <h1 className="mb-4 text-lg font-semibold">{t("title")}</h1>
        <nav className="flex gap-4 overflow-x-auto md:flex-col md:gap-5" aria-label={t("title")}>
          {SETTINGS_GROUPS.map((g) => (
            <div key={g.group} className="flex shrink-0 flex-col gap-0.5">
              <p className="mb-1 px-2 text-xs font-medium uppercase tracking-wide text-fg-subtle">{t(`groups.${g.group}`)}</p>
              {g.items.map((item) => (
                <Link
                  key={item.key}
                  href={item.href}
                  aria-current={pathname.startsWith(item.href) ? "page" : undefined}
                  className={cn(
                    "whitespace-nowrap rounded-md px-2 py-1.5 text-sm text-fg-muted hover:bg-subtle hover:text-fg",
                    pathname.startsWith(item.href) && "bg-subtle font-medium text-fg",
                  )}
                >
                  {t(`sections.${item.key}`)}
                </Link>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <section className="min-w-0 flex-1">{children}</section>
    </div>
  );
}

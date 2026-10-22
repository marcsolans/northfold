import { Logo } from "@messer/ui";
import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type * as React from "react";

export const metadata: Metadata = { robots: { index: false, follow: false } };

export default async function OnboardingLayout({ children }: { children: React.ReactNode }) {
  const t = await getTranslations("onboarding");
  return (
    <div className="flex min-h-screen flex-col bg-subtle">
      <header className="border-b border-border bg-bg">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4 sm:px-6">
          <Link href="/app" aria-label="Messer">
            <Logo />
          </Link>
          <Link href="/app" className="text-sm text-fg-muted hover:text-fg">
            {t("exit")}
          </Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6 sm:py-12">{children}</main>
    </div>
  );
}

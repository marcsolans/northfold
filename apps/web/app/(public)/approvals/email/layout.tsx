import { Logo } from "@messer/ui";
import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type * as React from "react";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("approvals.email");
  return { title: t("metaTitle"), robots: { index: false, follow: false }, referrer: "no-referrer" };
}

export default function ApprovalEmailLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-subtle">
      <header className="px-4 py-4 sm:px-6 sm:py-5">
        <Link href="/" aria-label="Messer">
          <Logo />
        </Link>
      </header>
      <main className="flex flex-1 items-start justify-center px-4 pb-16 pt-2 sm:pt-8">
        <div className="w-full max-w-lg">{children}</div>
      </main>
    </div>
  );
}

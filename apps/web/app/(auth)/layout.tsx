import { Logo } from "@messer/ui";
import Link from "next/link";
import type * as React from "react";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-subtle">
      <header className="px-6 py-5">
        <Link href="/" aria-label="Messer">
          <Logo />
        </Link>
      </header>
      <main className="flex flex-1 items-start justify-center px-4 pb-16 pt-6 sm:pt-12">
        <div className="w-full max-w-sm">{children}</div>
      </main>
    </div>
  );
}

import Link from "next/link";
import { type ReactNode, Suspense } from "react";
import { HiArrowRightOnRectangle, HiArrowTopRightOnSquare } from "react-icons/hi2";

import { SignOutButton } from "@/components/auth/sign-out-button";
import { Logo } from "@/components/layout/logo";
import { Badge } from "@/components/ui/badge";

import { AdminNav, AdminNavList } from "./admin-nav";

/** Admin chrome: sidebar on large screens, top bar with scrollable nav below. No storefront navbar. */
export function AdminShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col lg:flex-row">
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-border bg-card lg:flex">
        <div className="px-6 py-6">
          <Logo href="/admin" />
          <p className="mt-2 pl-[2.125rem] text-[0.65rem] font-medium tracking-[0.25em] text-accent uppercase">
            Admin
          </p>
        </div>
        <div className="flex-1 px-3">
          <Suspense fallback={<AdminNavList orientation="vertical" />}>
            <AdminNav orientation="vertical" />
          </Suspense>
        </div>
        <div className="space-y-1 border-t border-border px-3 py-4 text-sm">
          <Link
            href="/"
            className="flex items-center gap-3 rounded-md px-3 py-2 text-muted-foreground hover:bg-surface hover:text-foreground"
          >
            <HiArrowTopRightOnSquare aria-hidden="true" className="size-5" />
            View store
          </Link>
          <SignOutButton className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-muted-foreground hover:bg-surface hover:text-foreground">
            <HiArrowRightOnRectangle aria-hidden="true" className="size-5" />
            Sign out
          </SignOutButton>
        </div>
      </aside>
      <div className="sticky top-0 z-30 border-b border-border bg-card lg:hidden">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <Logo href="/admin" />
            <Badge tone="accent">Admin</Badge>
          </div>
          <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
            View store
          </Link>
        </div>
        <div className="px-2 pb-2">
          <Suspense fallback={<AdminNavList orientation="horizontal" />}>
            <AdminNav orientation="horizontal" />
          </Suspense>
        </div>
      </div>
      <main id="main" className="min-w-0 flex-1 bg-background">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-10 lg:py-10">{children}</div>
      </main>
    </div>
  );
}

export function AdminPageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-light tracking-tight sm:text-3xl">{title}</h1>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 gap-2">{actions}</div> : null}
    </div>
  );
}

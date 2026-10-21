import { Suspense } from "react";

import { AccountNav, AccountNavList } from "@/components/account/account-nav";
import { SignOutButton } from "@/components/auth/sign-out-button";
import { StoreShell } from "@/components/layout/store-shell";

export default function AccountLayout({ children }: LayoutProps<"/account">) {
  return (
    <StoreShell>
      <div className="mx-auto max-w-6xl px-4 pt-10 pb-16 sm:px-6">
        <p className="text-xs font-medium tracking-[0.25em] text-accent uppercase">Your account</p>
        <div className="mt-6 grid gap-8 lg:grid-cols-[12rem_1fr] lg:gap-12">
          <aside className="border-b border-border pb-4 lg:border-r lg:border-b-0 lg:pr-6 lg:pb-0">
            <Suspense fallback={<AccountNavList />}>
              <AccountNav />
            </Suspense>
            <SignOutButton className="mt-4 hidden px-3 text-sm text-muted-foreground hover:text-foreground lg:block" />
          </aside>
          <div className="min-w-0">{children}</div>
        </div>
      </div>
    </StoreShell>
  );
}

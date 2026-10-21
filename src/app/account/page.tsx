import type { Metadata } from "next";
import { Suspense } from "react";

import { SignOutButton } from "@/components/auth/sign-out-button";
import { Skeleton } from "@/components/ui/skeleton";
import { requireUserPage } from "@/server/auth/session";

export const metadata: Metadata = { title: "Your account", robots: { index: false } };

async function AccountOverview() {
  const user = await requireUserPage("/account");
  return (
    <div>
      <h1 className="text-3xl font-light tracking-tight">Hello, {user.name}</h1>
      <p className="mt-2 text-muted-foreground">Signed in as {user.email}</p>
      <SignOutButton className="mt-6 text-sm underline underline-offset-4" />
    </div>
  );
}

export default function AccountPage() {
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-16 sm:px-6">
      <Suspense fallback={<Skeleton className="h-24 w-full" />}>
        <AccountOverview />
      </Suspense>
    </div>
  );
}

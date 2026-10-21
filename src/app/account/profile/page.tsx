import type { Metadata } from "next";
import { Suspense } from "react";

import { PasswordForm } from "@/components/account/password-form";
import { ProfileForm } from "@/components/account/profile-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/format";
import { requireUserPage } from "@/server/auth/session";
import { getMemberSince, hasPasswordAccount } from "@/server/queries/account";

export const metadata: Metadata = { title: "Profile", robots: { index: false } };

async function Profile() {
  const user = await requireUserPage("/account/profile");
  const [hasPassword, memberSince] = await Promise.all([
    hasPasswordAccount(user.id),
    getMemberSince(user.id),
  ]);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Personal details</CardTitle>
          {memberSince ? (
            <CardDescription>Member since {formatDate(memberSince)}</CardDescription>
          ) : null}
        </CardHeader>
        <CardContent className="max-w-md">
          <ProfileForm key={user.name} name={user.name} email={user.email} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Password</CardTitle>
          <CardDescription>
            {hasPassword
              ? "Changing your password signs you out on your other devices."
              : "You sign in with Google, so there is no Northfold password to change."}
          </CardDescription>
        </CardHeader>
        {hasPassword ? (
          <CardContent className="max-w-md">
            <PasswordForm />
          </CardContent>
        ) : null}
      </Card>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <>
      <h1 className="mb-6 text-3xl font-light tracking-tight">Profile</h1>
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <Profile />
      </Suspense>
    </>
  );
}

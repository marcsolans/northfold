import Link from "next/link";
import { redirect } from "next/navigation";

import { features } from "@/env";
import { safeRedirectPath } from "@/lib/validators/auth";
import { firstParam, type RawParam } from "@/lib/validators/common";
import { getCurrentUser } from "@/server/auth/session";

import { AuthCard } from "./auth-card";
import { oauthErrorMessage } from "./auth-errors";
import { GoogleButton, OrDivider } from "./google-button";
import { SignInForm } from "./sign-in-form";
import { SignUpForm } from "./sign-up-form";

const DEFAULT_REDIRECT = "/account";

/** Shared server body of the sign-in and sign-up pages (rendered inside Suspense). */
export async function AuthPage({
  mode,
  searchParams,
}: {
  mode: "sign-in" | "sign-up";
  searchParams: Promise<Record<string, RawParam>>;
}) {
  const params = await searchParams;
  const redirectTo = safeRedirectPath(firstParam(params.redirectTo), DEFAULT_REDIRECT);
  if (await getCurrentUser()) redirect(redirectTo);

  const oauthError = oauthErrorMessage(firstParam(params.error));
  const otherHref = `/${mode === "sign-in" ? "sign-up" : "sign-in"}${
    redirectTo === DEFAULT_REDIRECT ? "" : `?redirectTo=${encodeURIComponent(redirectTo)}`
  }`;

  return (
    <AuthCard
      title={mode === "sign-in" ? "Welcome back" : "Create your account"}
      description={
        mode === "sign-in"
          ? "Sign in to check out faster and follow your orders."
          : "Save your addresses, check out faster and follow your orders."
      }
      footer={
        mode === "sign-in" ? (
          <>
            New to Northfold?{" "}
            <Link
              href={otherHref}
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              Create an account
            </Link>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <Link
              href={otherHref}
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              Sign in
            </Link>
          </>
        )
      }
    >
      {oauthError ? (
        <p
          role="alert"
          className="mb-6 rounded-md bg-destructive-soft px-4 py-3 text-sm text-destructive"
        >
          {oauthError}
        </p>
      ) : null}
      {features.googleAuth ? (
        <>
          <GoogleButton redirectTo={redirectTo} />
          <OrDivider />
        </>
      ) : null}
      {mode === "sign-in" ? (
        <SignInForm redirectTo={redirectTo} />
      ) : (
        <SignUpForm redirectTo={redirectTo} />
      )}
    </AuthCard>
  );
}

"use client";

import { Alert, Spinner } from "@messer/ui";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { ApiError, http } from "@/lib/api";

/** Supabase OAuth returns tokens in the URL fragment; hand them to the API to set httpOnly cookies. */
export default function AuthCallbackPage() {
  const t = useTranslations("auth");
  const router = useRouter();
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.slice(1));
    const search = new URLSearchParams(window.location.search);
    const access = hash.get("access_token");
    const refresh = hash.get("refresh_token");
    const next = search.get("next") ?? "/app";
    if (!access || !refresh) {
      setError(t("verifyError"));
      return;
    }
    http
      .post<{ redirect: string | null }>("/auth/supabase/session", { access_token: access, refresh_token: refresh })
      .then((res) => {
        window.history.replaceState(null, "", window.location.pathname);
        router.replace(res.redirect === "/onboarding" ? "/onboarding" : next);
      })
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : String(err)));
  }, [router, t]);

  return (
    <AuthCard title={t("callbackWorking")}>
      {error ? <Alert tone="danger">{error}</Alert> : <Spinner />}
    </AuthCard>
  );
}

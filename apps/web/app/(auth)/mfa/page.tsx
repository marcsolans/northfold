"use client";

import { Alert, Button, Field, Input } from "@messer/ui";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";
import { Suspense } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { ApiError, http } from "@/lib/api";

function MfaForm() {
  const t = useTranslations("auth");
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const token = params.get("token") ?? "";
  const next = params.get("next") ?? "/app";

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const code = String(new FormData(e.currentTarget).get("code"));
    setLoading(true);
    setError(null);
    try {
      await http.post("/auth/mfa/verify", { mfa_token: token, code });
      router.push(next.startsWith("/") ? next : "/app");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCard title={t("mfaTitle")} subtitle={t("mfaSubtitle")}>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Field label={t("mfaCode")} htmlFor="code">
          <Input id="code" name="code" inputMode="numeric" autoComplete="one-time-code" autoFocus required />
        </Field>
        <Button type="submit" variant="primary" loading={loading}>
          {t("verify")}
        </Button>
      </form>
    </AuthCard>
  );
}

export default function MfaPage() {
  return (
    <Suspense>
      <MfaForm />
    </Suspense>
  );
}

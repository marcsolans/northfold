"use client";

import { Alert, Button, Field, Input } from "@messer/ui";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";
import { Suspense } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { ApiError, http } from "@/lib/api";

function ResetForm() {
  const t = useTranslations("auth");
  const params = useSearchParams();
  const [done, setDone] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await http.post("/auth/password/reset", {
        token: params.get("token") ?? "",
        password: String(new FormData(e.currentTarget).get("password")),
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCard title={t("resetTitle")}>
      {done ? (
        <div className="flex flex-col gap-3">
          <Alert tone="success">{t("resetDone")}</Alert>
          <Button asChild variant="primary">
            <Link href="/login">{t("login")}</Link>
          </Button>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Field label={t("password")} htmlFor="password" hint={t("passwordHint")}>
            <Input id="password" name="password" type="password" autoComplete="new-password" required />
          </Field>
          <Button type="submit" variant="primary" loading={loading}>
            {t("setPassword")}
          </Button>
        </form>
      )}
    </AuthCard>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetForm />
    </Suspense>
  );
}

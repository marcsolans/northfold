"use client";

import { Alert, Button, Field, Input } from "@messer/ui";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { ApiError, http } from "@/lib/api";

export default function ForgotPasswordPage() {
  const t = useTranslations("auth");
  const [sent, setSent] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await http.post("/auth/password/forgot", { email: String(new FormData(e.currentTarget).get("email")) });
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCard
      title={t("forgotTitle")}
      subtitle={t("forgotSubtitle")}
      footer={
        <Link href="/login" className="underline underline-offset-4">
          {t("login")}
        </Link>
      }
    >
      {sent ? (
        <Alert tone="success">{t("linkSent")}</Alert>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Field label={t("email")} htmlFor="email">
            <Input id="email" name="email" type="email" autoComplete="email" required />
          </Field>
          <Button type="submit" variant="primary" loading={loading}>
            {t("sendLink")}
          </Button>
        </form>
      )}
    </AuthCard>
  );
}

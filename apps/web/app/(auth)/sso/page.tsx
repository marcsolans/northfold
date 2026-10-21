"use client";

import { Alert, Button, Field, Input } from "@messer/ui";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { ApiError, http } from "@/lib/api";

export default function SsoPage() {
  const t = useTranslations("auth");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const email = String(new FormData(e.currentTarget).get("email"));
      const res = await http.post<{ redirect_url: string }>("/sso/discover", { email });
      window.location.href = res.redirect_url;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setLoading(false);
    }
  }

  return (
    <AuthCard title={t("ssoTitle")} subtitle={t("ssoSubtitle")}>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Field label={t("email")} htmlFor="email">
          <Input id="email" name="email" type="email" autoComplete="email" required />
        </Field>
        <Button type="submit" variant="primary" loading={loading}>
          {t("ssoContinue")}
        </Button>
      </form>
    </AuthCard>
  );
}

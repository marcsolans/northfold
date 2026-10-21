"use client";

import { Alert, Button, Field, Input } from "@messer/ui";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { Divider, SocialButtons } from "@/components/auth/social-buttons";
import { ApiError, http } from "@/lib/api";

interface AuthOut {
  mfa_required: boolean;
  mfa_token: string | null;
  redirect: string | null;
}

export function LoginForm() {
  const t = useTranslations("auth");
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/app";
  const [error, setError] = React.useState<string | null>(params.get("error") ? t("verifyError") : null);
  const [loading, setLoading] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setLoading(true);
    setError(null);
    try {
      const res = await http.post<AuthOut>("/auth/login", {
        email: String(form.get("email")),
        password: String(form.get("password")),
      });
      if (res.mfa_required && res.mfa_token) {
        router.push(`/mfa?token=${encodeURIComponent(res.mfa_token)}&next=${encodeURIComponent(next)}`);
        return;
      }
      router.push(next.startsWith("/") ? next : "/app");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCard
      title={t("loginTitle")}
      subtitle={t("loginSubtitle")}
      footer={
        <>
          {t("noAccount")}{" "}
          <Link className="font-medium text-fg underline underline-offset-4" href="/signup">
            {t("signup")}
          </Link>
        </>
      }
    >
      <SocialButtons next={next} />
      <Divider label={t("orContinue")} />
      <form onSubmit={onSubmit} className="flex flex-col gap-3" noValidate>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Field label={t("email")} htmlFor="email">
          <Input id="email" name="email" type="email" autoComplete="email" required />
        </Field>
        <Field label={t("password")} htmlFor="password">
          <Input id="password" name="password" type="password" autoComplete="current-password" required />
        </Field>
        <Button type="submit" variant="primary" loading={loading} className="mt-1">
          {t("login")}
        </Button>
        <Link href="/forgot-password" className="text-center text-sm text-fg-muted hover:text-fg">
          {t("forgot")}
        </Link>
      </form>
    </AuthCard>
  );
}

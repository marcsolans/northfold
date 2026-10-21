"use client";

import { Alert, Button, Field, Input } from "@messer/ui";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { Divider, SocialButtons } from "@/components/auth/social-buttons";
import { ApiError, http } from "@/lib/api";

export function SignupForm() {
  const t = useTranslations("auth");
  const locale = useLocale();
  const router = useRouter();
  const params = useSearchParams();
  const invitation = params.get("invitation");
  const plan = params.get("plan");
  const [error, setError] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [loading, setLoading] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const password = String(form.get("password"));
    const errors: Record<string, string> = {};
    if (password.length < 10 || password.toLowerCase() === password || !/\d/.test(password)) {
      errors.password = t("passwordHint");
    }
    setFieldErrors(errors);
    if (Object.keys(errors).length) return;
    setLoading(true);
    setError(null);
    try {
      const res = await http.post<{ redirect: string | null }>("/auth/signup", {
        email: String(form.get("email")),
        password,
        name: String(form.get("name") || "") || null,
        org_name: invitation ? null : String(form.get("org_name") || "") || null,
        locale: locale === "en" ? "en" : "es",
        invitation_token: invitation,
        accept_terms: true,
      });
      const target = plan ? `/app/settings/billing?plan=${encodeURIComponent(plan)}` : (res.redirect ?? "/onboarding");
      router.push(target);
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCard
      title={t("signupTitle")}
      subtitle={t("signupSubtitle")}
      footer={
        <>
          {t("haveAccount")}{" "}
          <Link className="font-medium text-fg underline underline-offset-4" href="/login">
            {t("login")}
          </Link>
        </>
      }
    >
      {!invitation ? (
        <>
          <SocialButtons next="/onboarding" />
          <Divider label={t("orContinue")} />
        </>
      ) : null}
      <form onSubmit={onSubmit} className="flex flex-col gap-3" noValidate>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <Field label={t("name")} htmlFor="name">
          <Input id="name" name="name" autoComplete="name" required />
        </Field>
        <Field label={t("email")} htmlFor="email">
          <Input id="email" name="email" type="email" autoComplete="email" required />
        </Field>
        {!invitation ? (
          <Field label={t("orgName")} htmlFor="org_name">
            <Input id="org_name" name="org_name" autoComplete="organization" />
          </Field>
        ) : null}
        <Field label={t("password")} htmlFor="password" hint={t("passwordHint")} error={fieldErrors.password}>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="new-password"
            required
            aria-invalid={Boolean(fieldErrors.password)}
          />
        </Field>
        <Button type="submit" variant="primary" loading={loading} className="mt-1">
          {t("signup")}
        </Button>
        <p className="text-xs text-fg-subtle">
          {t.rich("terms", {
            terms: (chunks) => (
              <Link href="/legal/terms" className="underline underline-offset-2">
                {chunks}
              </Link>
            ),
            privacy: (chunks) => (
              <Link href="/legal/privacy" className="underline underline-offset-2">
                {chunks}
              </Link>
            ),
          })}
        </p>
      </form>
    </AuthCard>
  );
}

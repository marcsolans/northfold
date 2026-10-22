"use client";

import { Alert, Button, Skeleton } from "@messer/ui";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AuthCard } from "@/components/auth/auth-card";

const KNOWN = new Set([
  "state_expired",
  "state_mismatch",
  "connection_unavailable",
  "plan_feature",
  "domain_not_verified",
  "domain_mismatch",
  "hosted_domain_mismatch",
  "jit_disabled",
  "deprovisioned",
  "user_blocked",
  "user_deleted",
  "org_unavailable",
  "sso_required",
  "idp_denied",
  "idp_unreachable",
  "invalid_signature",
  "assertion_expired",
  "assertion_replayed",
  "audience_mismatch",
  "not_authenticated",
  "forbidden",
  "missing_email",
  "email_unverified",
]);

export default function SsoErrorPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-48 w-full" />}>
      <SsoError />
    </React.Suspense>
  );
}

function SsoError() {
  const t = useTranslations("enterprise.ssoError");
  const code = useSearchParams().get("code") ?? "unknown";
  const message = KNOWN.has(code) ? t(`codes.${code}`) : t("generic");
  return (
    <AuthCard title={code === "sso_required" ? t("requiredTitle") : t("title")}>
      <div className="flex flex-col gap-4">
        <Alert tone={code === "sso_required" ? "info" : "danger"}>{message}</Alert>
        <p className="text-xs text-fg-subtle">{t("code", { code })}</p>
        <div className="flex flex-col gap-2">
          <Button asChild variant="primary">
            <Link href="/sso">{code === "sso_required" ? t("useSso") : t("retry")}</Link>
          </Button>
          {code !== "sso_required" ? (
            <Button asChild variant="secondary">
              <Link href="/login">{t("login")}</Link>
            </Button>
          ) : null}
        </div>
      </div>
    </AuthCard>
  );
}

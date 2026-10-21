"use client";

import { Alert, Button, SkeletonRows } from "@messer/ui";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { ApiError, http } from "@/lib/api";
import type { Me } from "@/lib/types";

interface Lookup {
  org_name: string;
  email: string;
  role: string;
  expired: boolean;
  accepted: boolean;
}

export default function InvitePage() {
  const t = useTranslations("auth");
  const tc = useTranslations("common");
  const router = useRouter();
  const { token } = useParams<{ token: string }>();
  const lookup = useQuery({ queryKey: ["invite", token], queryFn: () => http.get<Lookup>(`/invitations/lookup/${token}`) });
  const me = useQuery({ queryKey: ["me"], queryFn: () => http.get<Me>("/me"), retry: false });
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  if (lookup.isLoading) return <SkeletonRows rows={3} />;
  const data = lookup.data;
  if (!data || data.expired || data.accepted) {
    return (
      <AuthCard title={t("verifyTitle")}>
        <Alert tone="danger">{t("inviteInvalid")}</Alert>
      </AuthCard>
    );
  }
  const roleLabel = tc(`roles.${data.role}` as "roles.viewer");

  async function accept() {
    setLoading(true);
    setError(null);
    try {
      await http.post("/auth/invitations/accept", { token });
      router.push("/app");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCard title={t("inviteTitle", { org: data.org_name })} subtitle={t("inviteBody", { role: roleLabel, email: data.email })}>
      {error ? <Alert tone="danger" className="mb-3">{error}</Alert> : null}
      {me.data ? (
        <Button variant="primary" className="w-full" loading={loading} onClick={accept}>
          {t("inviteAcceptLoggedIn")}
        </Button>
      ) : (
        <div className="flex flex-col gap-2">
          <Button asChild variant="primary">
            <Link href={`/signup?invitation=${encodeURIComponent(token)}`}>{t("inviteCreate")}</Link>
          </Button>
          <Button asChild variant="secondary">
            <Link href={`/login?next=${encodeURIComponent(`/invite/${token}`)}`}>{t("inviteLogin")}</Link>
          </Button>
        </div>
      )}
    </AuthCard>
  );
}

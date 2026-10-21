"use client";

import { Alert, Button, Spinner } from "@messer/ui";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";
import { Suspense } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { http } from "@/lib/api";

function Verify() {
  const t = useTranslations("auth");
  const params = useSearchParams();
  const [state, setState] = React.useState<"working" | "done" | "error">("working");
  const token = params.get("token");

  React.useEffect(() => {
    if (!token) {
      setState("error");
      return;
    }
    http.post("/auth/verify-email", { token }).then(
      () => setState("done"),
      () => setState("error"),
    );
  }, [token]);

  return (
    <AuthCard title={t("verifyTitle")}>
      {state === "working" ? <Spinner /> : null}
      {state === "done" ? <Alert tone="success">{t("verifyDone")}</Alert> : null}
      {state === "error" ? <Alert tone="danger">{t("verifyError")}</Alert> : null}
      {state !== "working" ? (
        <Button asChild variant="primary" className="mt-4 w-full">
          <Link href="/app">{t("goToApp")}</Link>
        </Button>
      ) : null}
    </AuthCard>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <Verify />
    </Suspense>
  );
}

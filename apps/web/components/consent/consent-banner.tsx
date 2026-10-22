"use client";

import { Button } from "@messer/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { type Consent, readConsent, startAnalytics, writeConsent } from "@/lib/analytics";

export function ConsentBanner() {
  const t = useTranslations("consent");
  const [consent, setConsent] = React.useState<Consent | null | undefined>(undefined);
  // Embedded widgets live inside customers' pages, which own the visitor's consent.
  const embedded = usePathname()?.startsWith("/embed/") ?? false;

  React.useEffect(() => {
    const value = readConsent();
    setConsent(value);
    if (value === "accepted") void startAnalytics();
  }, []);

  if (consent !== null || embedded) return null;

  const decide = (value: Consent) => {
    writeConsent(value);
    setConsent(value);
    if (value === "accepted") void startAnalytics();
  };

  return (
    <div
      role="dialog"
      aria-live="polite"
      aria-label={t("title")}
      className="fixed inset-x-3 bottom-3 z-50 mx-auto max-w-2xl rounded-md border border-border bg-surface p-4 shadow-lg sm:inset-x-6"
    >
      <p className="text-sm font-semibold">{t("title")}</p>
      <p className="mt-1 text-sm text-fg-muted">
        {t("body")}{" "}
        <Link href="/legal/cookies" className="underline underline-offset-4">
          {t("policy")}
        </Link>
      </p>
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <Button variant="secondary" onClick={() => decide("rejected")}>
          {t("reject")}
        </Button>
        <Button variant="dark" onClick={() => decide("accepted")}>
          {t("accept")}
        </Button>
      </div>
    </div>
  );
}

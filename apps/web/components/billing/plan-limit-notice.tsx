"use client";

import { Alert, Button } from "@messer/ui";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { billingHref, planLimitInfo } from "./upgrade-dialog";

/**
 * Inline notice for a 402 from the API (plan limit, missing feature or read-only billing state).
 * Renders nothing for other errors, so it can sit next to any form: ``<PlanLimitNotice error={mutation.error} />``.
 */
export function PlanLimitNotice({ error, className }: { error: unknown; className?: string }) {
  const t = useTranslations("billing");
  const info = planLimitInfo(error);
  if (!info) return null;
  return (
    <Alert
      tone="warning"
      className={className}
      title={info.code === "read_only" ? t("upgrade.readOnlyTitle") : t("upgrade.limitTitle")}
      action={
        <Button asChild size="sm" variant="dark">
          <Link href={billingHref(info.details.upgrade_to)}>
            {info.code === "read_only" ? t("upgrade.choosePlan") : t("upgrade.seePlans")}
            <ArrowUpRight />
          </Link>
        </Button>
      }
    >
      {info.message}
    </Alert>
  );
}

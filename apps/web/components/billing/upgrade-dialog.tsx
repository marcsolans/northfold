"use client";

import { Alert, Badge, Button, Dialog, DialogContent, Skeleton } from "@messer/ui";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Check } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatEur, formatNumber, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { FEATURE_KEYS, type LimitKey, type Plan, PLANS_KEY, isUnlimited } from "./types";

export interface PlanLimitDetails {
  feature?: string;
  limit?: LimitKey;
  value?: number;
  used?: number;
  upgrade_to?: string | null;
  current_plan?: string | null;
}

export interface PlanLimitInfo {
  code: "plan_limit" | "read_only" | "payment_required";
  message: string;
  details: PlanLimitDetails;
}

/** The API answers 402 ``plan_limit`` (limit or feature) or ``read_only`` (billing state). */
export function planLimitInfo(error: unknown): PlanLimitInfo | null {
  if (!(error instanceof ApiError) || error.status !== 402) return null;
  const code = error.code === "plan_limit" || error.code === "read_only" ? error.code : "payment_required";
  return { code, message: error.message, details: error.details as PlanLimitDetails };
}

export function isPlanLimitError(error: unknown): boolean {
  return planLimitInfo(error) !== null;
}

export function billingHref(planId?: string | null): string {
  return planId ? `/app/settings/billing?plan=${encodeURIComponent(planId)}#plans` : "/app/settings/billing#plans";
}

function UpgradeTarget({ planId }: { planId: string }) {
  const t = useTranslations("billing");
  const locale = localeTag(useLocale());
  const plans = useQuery({ queryKey: PLANS_KEY, queryFn: () => http.get<Plan[]>("/plans"), staleTime: 300_000 });
  if (plans.isLoading) return <Skeleton className="h-24 w-full" />;
  const plan = plans.data?.find((p) => p.id === planId);
  if (!plan) return null;
  const limits: LimitKey[] = ["seats", "projects", "runs_month", "credits_month"];
  return (
    <div className="rounded-md border border-border bg-subtle p-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="font-semibold">{plan.name}</p>
        <p className="tabular text-sm">
          {plan.price_is_starting ? `${t("plans.from")} ` : ""}
          {formatEur(plan.price_month_eur, locale)}
          <span className="text-fg-muted"> {t("plans.perMonth")}</span>
        </p>
      </div>
      <ul className="mt-2 grid gap-1 text-sm text-fg-muted sm:grid-cols-2">
        {limits.map((key) => (
          <li key={key} className="flex items-center gap-1.5">
            <Check className="size-3.5 text-success" aria-hidden />
            {isUnlimited(plan.limits[key])
              ? t(`limitsUnlimited.${key}`)
              : t(`limitsCount.${key}`, { count: plan.limits[key], value: formatNumber(plan.limits[key], locale) })}
          </li>
        ))}
        {plan.limits.features
          .filter((f) => (FEATURE_KEYS as readonly string[]).includes(f))
          .slice(0, 4)
          .map((f) => (
            <li key={f} className="flex items-center gap-1.5">
              <Check className="size-3.5 text-success" aria-hidden />
              {t(`features.${f}`)}
            </li>
          ))}
      </ul>
    </div>
  );
}

/** Shown when an action is refused by the plan (402). ``error`` comes straight from the API call. */
export function UpgradeDialog({
  open,
  onOpenChange,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  error: unknown;
}) {
  const t = useTranslations("billing");
  const isOwner = useRole("owner");
  const info = planLimitInfo(error);
  const target = info?.details.upgrade_to ?? null;
  const title =
    info?.code === "read_only"
      ? t("upgrade.readOnlyTitle")
      : info?.details.feature
        ? t("upgrade.featureTitle")
        : t("upgrade.limitTitle");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={title}
        description={info?.message}
        footer={
          <>
            <Button variant="secondary" onClick={() => onOpenChange(false)}>
              {t("upgrade.notNow")}
            </Button>
            <Button asChild variant="primary">
              <Link href={billingHref(target)} onClick={() => onOpenChange(false)}>
                {info?.code === "read_only" ? t("upgrade.choosePlan") : t("upgrade.seePlans")}
                <ArrowUpRight />
              </Link>
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          {target ? (
            <>
              <p className="text-sm text-fg-muted">
                {t("upgrade.recommended")} <Badge tone="accent">{target}</Badge>
              </p>
              <UpgradeTarget planId={target} />
            </>
          ) : null}
          {!isOwner ? <Alert tone="info">{t("upgrade.askOwner")}</Alert> : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Hook for pages that call the API: ``const upgrade = useUpgradeDialog();`` then in ``onError``:
 * ``if (!upgrade.handle(err)) toast.error(...)``, and render ``{upgrade.dialog}`` once.
 */
export function useUpgradeDialog(): { handle: (error: unknown) => boolean; dialog: React.ReactNode } {
  const [error, setError] = React.useState<unknown>(null);
  const handle = React.useCallback((err: unknown) => {
    if (!isPlanLimitError(err)) return false;
    setError(err);
    return true;
  }, []);
  const dialog = <UpgradeDialog open={error !== null} onOpenChange={(open) => !open && setError(null)} error={error} />;
  return { handle, dialog };
}

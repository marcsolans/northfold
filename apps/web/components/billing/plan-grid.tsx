"use client";

import { Badge, Button, cn } from "@messer/ui";
import { Check, Minus } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { formatEur, formatNumber, localeTag } from "@/lib/format";

import { FEATURE_KEYS, type Interval, type LimitKey, type Plan, annualDiscountPct, isUnlimited, monthlyEquivalent } from "./types";

const LIMIT_ROWS: LimitKey[] = ["seats", "projects", "runs_month", "credits_month", "storage_gb"];

export interface PlanAction {
  label: string;
  onClick?: () => void;
  href?: string;
  disabled?: boolean;
  loading?: boolean;
  variant?: "primary" | "secondary" | "dark";
}

/** Monthly / annual switch showing the best annual discount. */
export function IntervalToggle({
  value,
  onChange,
  plans,
}: {
  value: Interval;
  onChange: (value: Interval) => void;
  plans: Plan[];
}) {
  const t = useTranslations("billing");
  const discount = Math.max(0, ...plans.filter((p) => p.self_serve).map(annualDiscountPct));
  return (
    <div role="radiogroup" aria-label={t("plans.interval")} className="inline-flex rounded-md border border-border bg-subtle p-0.5">
      {(["month", "year"] as const).map((interval) => (
        <button
          key={interval}
          type="button"
          role="radio"
          aria-checked={value === interval}
          onClick={() => onChange(interval)}
          className={cn(
            "rounded-sm px-3 py-1 text-sm text-fg-muted",
            value === interval && "bg-surface font-medium text-fg shadow-[0_0_0_1px_var(--border)]",
          )}
        >
          {t(`interval.${interval}`)}
          {interval === "year" && discount > 0 ? (
            <span className="ml-1.5 text-xs font-medium text-success">−{discount}%</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

/** Plan comparison with prices in plain view. ``actionFor`` decides each card's button. */
export function PlanGrid({
  plans,
  interval,
  currentPlanId,
  highlightId,
  actionFor,
}: {
  plans: Plan[];
  interval: Interval;
  currentPlanId: string | null;
  highlightId?: string | null;
  actionFor: (plan: Plan) => PlanAction;
}) {
  const t = useTranslations("billing");
  const locale = localeTag(useLocale());
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {plans.map((plan) => {
        const action = actionFor(plan);
        const yearly = interval === "year" && !plan.price_is_starting;
        const discount = annualDiscountPct(plan);
        const highlighted = highlightId === plan.id;
        return (
          <div
            key={plan.id}
            id={`plan-${plan.id}`}
            className={cn(
              "flex flex-col rounded-md border border-border bg-surface p-4",
              (highlighted || currentPlanId === plan.id) && "border-fg",
              highlighted && "ring-1 ring-fg",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-md font-semibold">{plan.name}</h3>
              {currentPlanId === plan.id ? <Badge tone="info">{t("plans.current")}</Badge> : null}
            </div>
            <p className="mt-1 min-h-10 text-sm text-fg-muted">{plan.description}</p>
            <div className="mt-3">
              <p className="h-4 text-xs text-fg-muted">{plan.price_is_starting ? t("plans.from") : null}</p>
              <p className="tabular whitespace-nowrap text-xl font-semibold">
                {formatEur(monthlyEquivalent(plan, yearly ? "year" : "month"), locale)}
                <span className="text-sm font-normal text-fg-muted"> {t("plans.perMonth")}</span>
              </p>
              <p className="tabular mt-0.5 min-h-5 text-xs text-fg-subtle">
                {yearly
                  ? t("plans.billedYearly", { amount: formatEur(plan.price_year_eur, locale), discount })
                  : t("plans.vatExcluded")}
              </p>
            </div>
            <div className="mt-4">
              {action.href ? (
                <Button asChild variant={action.variant ?? "secondary"} className="w-full">
                  <Link href={action.href}>{action.label}</Link>
                </Button>
              ) : (
                <Button
                  variant={action.variant ?? "secondary"}
                  className="w-full"
                  disabled={action.disabled}
                  loading={action.loading}
                  onClick={action.onClick}
                >
                  {action.label}
                </Button>
              )}
            </div>
            <ul className="mt-4 flex flex-col gap-1.5 border-t border-border pt-3 text-sm">
              {LIMIT_ROWS.map((key) => (
                <li key={key} className="flex items-center gap-2">
                  <Check className="size-3.5 shrink-0 text-success" aria-hidden />
                  {isUnlimited(plan.limits[key])
                    ? t(`limitsUnlimited.${key}`)
                    : t(`limitsCount.${key}`, { count: plan.limits[key], value: formatNumber(plan.limits[key], locale) })}
                </li>
              ))}
              {FEATURE_KEYS.map((feature) => {
                const included = plan.limits.features.includes(feature);
                return (
                  <li key={feature} className={cn("flex items-center gap-2", !included && "text-fg-subtle")}>
                    {included ? (
                      <Check className="size-3.5 shrink-0 text-success" aria-hidden />
                    ) : (
                      <Minus className="size-3.5 shrink-0" aria-hidden />
                    )}
                    <span>
                      {t(`features.${feature}`)}
                      <span className="sr-only"> — {included ? t("plans.included") : t("plans.notIncluded")}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

export function TestModeBadge() {
  const t = useTranslations("billing");
  return (
    <Badge tone="warning" title={t("testMode.hint")}>
      {t("testMode.badge")}
    </Badge>
  );
}

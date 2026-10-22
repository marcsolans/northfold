"use client";

import { useTranslations } from "next-intl";

import { usePendingApprovals } from "@/lib/studio/hooks";

/**
 * Pending approvals counter for the "Aprobaciones" item of the main navigation
 * (`GET /approvals` → `pending`). Renders nothing when there is nothing to decide.
 */
export function ApprovalsNavBadge({ className }: { className?: string }) {
  const t = useTranslations("approvals");
  const { data: pending } = usePendingApprovals();
  if (!pending) return null;
  return (
    <span
      className={
        className ??
        "tabular ml-auto inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-fg"
      }
      aria-label={t("pendingCount", { count: pending })}
    >
      {pending > 99 ? "99+" : pending}
    </span>
  );
}

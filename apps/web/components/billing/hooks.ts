"use client";

import type { StatusTone } from "@messer/ui";
import { useRouter } from "next/navigation";
import * as React from "react";

import { ApiError } from "@/lib/api";

/** Badge tone per derived subscription state. */
export const STATE_TONES: Record<string, StatusTone> = {
  active: "success",
  trialing: "info",
  past_due: "warning",
  incomplete: "warning",
  canceled: "danger",
  trial_expired: "danger",
  none: "neutral",
};

/** Billing and budget periods are computed in UTC; show them in UTC so the boundaries do not shift. */
export function formatUtcDate(value: string | number | Date, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(value));
}

/** Last day of a period whose end is exclusive (``[start, end)``). */
export function inclusiveEnd(end: string): Date {
  return new Date(new Date(end).getTime() - 1);
}

export function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

/** Follow a checkout URL: the simulated test-mode page is in-app, Stripe Checkout is external. */
export function useFollowCheckout(): (url: string) => void {
  const router = useRouter();
  return React.useCallback(
    (url: string) => {
      try {
        const target = new URL(url, window.location.origin);
        if (target.origin === window.location.origin || target.pathname.startsWith("/app/settings/billing/checkout/")) {
          router.push(`${target.pathname}${target.search}`);
          return;
        }
      } catch {
        // not a URL we can parse: let the browser navigate
      }
      window.location.assign(url);
    },
    [router],
  );
}

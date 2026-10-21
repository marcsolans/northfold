"use client";

import { useEffect, useState } from "react";

import { validateCart } from "@/server/actions/cart";
import type { CartChange, CartValidation } from "@/server/cart";
import { useCartStore } from "@/stores/cart-store";

import { useCartHydrated } from "./cart-hydrator";

export type CartValidationStatus = "validating" | "ready" | "error";

const EMPTY: CartValidation = { lines: [], changes: [] };

/**
 * After the persisted cart loads, re-validates it on the server (stock, availability, prices)
 * and replaces it with the authoritative result. Runs again whenever the page becomes visible
 * after a client navigation, because effects re-run when a hidden route is shown.
 */
export function useValidatedCart(): {
  status: CartValidationStatus;
  changes: CartChange[];
  /** Validates again, e.g. after checkout reported a stock problem. */
  revalidate: () => void;
} {
  const hydrated = useCartHydrated();
  const [round, setRound] = useState(0);
  const [state, setState] = useState<{ status: CartValidationStatus; changes: CartChange[] }>({
    status: "validating",
    changes: [],
  });

  useEffect(() => {
    if (!hydrated) return;
    let cancelled = false;
    const lines = useCartStore.getState().lines;
    const request =
      lines.length === 0
        ? Promise.resolve({ ok: true as const, data: EMPTY })
        : validateCart(
            lines.map((line) => ({
              variantId: line.variantId,
              quantity: line.quantity,
              knownPrice: line.snapshot.unitPrice,
              label: `${line.snapshot.productName} (${line.snapshot.size} / ${line.snapshot.colorName})`,
            })),
          );

    request
      .then((result) => {
        if (cancelled) return;
        if (!result.ok) {
          setState({ status: "error", changes: [] });
          return;
        }
        useCartStore.getState().replaceLines(result.data.lines);
        setState({ status: "ready", changes: result.data.changes });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error", changes: [] });
      });

    return () => {
      cancelled = true;
    };
  }, [hydrated, round]);

  return { ...state, revalidate: () => setRound((value) => value + 1) };
}

"use client";

import { useEffect } from "react";

import { useCartStore } from "@/stores/cart-store";

import { useCartHydrated } from "./cart-hydrator";

/** Empties the bag once an order is confirmed (rendered only on confirmed orders). */
export function ClearCart() {
  const hydrated = useCartHydrated();
  useEffect(() => {
    // Wait for the persisted cart to load, otherwise hydration would restore it afterwards.
    if (hydrated) useCartStore.getState().clear();
  }, [hydrated]);
  return null;
}

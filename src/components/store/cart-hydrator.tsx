"use client";

import { useEffect, useSyncExternalStore } from "react";

import { CART_STORAGE_KEY, useCartStore } from "@/stores/cart-store";

/**
 * Loads the persisted cart after mount (the store uses `skipHydration`), so the server render
 * and the first client render agree. Also keeps tabs in sync.
 */
export function CartHydrator() {
  useEffect(() => {
    void useCartStore.persist.rehydrate();
    const onStorage = (event: StorageEvent) => {
      if (event.key === CART_STORAGE_KEY) void useCartStore.persist.rehydrate();
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  return null;
}

/** True once the persisted cart has been loaded (always false during SSR). */
export function useCartHydrated(): boolean {
  return useSyncExternalStore(
    (onChange) => useCartStore.persist.onFinishHydration(onChange),
    () => useCartStore.persist.hasHydrated(),
    () => false,
  );
}

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { Size } from "@/generated/prisma/enums";
import { type MoneyString } from "@/lib/money";
import { calculateTotals, type OrderTotals } from "@/lib/pricing";
import { CATALOG } from "@/lib/store-config";

/**
 * Display-only snapshot captured when an item is added. The server never trusts it: prices,
 * stock and availability are re-validated before the cart page renders and at checkout.
 */
export interface CartSnapshot {
  productId: string;
  productName: string;
  productSlug: string;
  imageUrl: string | null;
  size: Size;
  colorName: string;
  unitPrice: MoneyString;
  /** Units available when the snapshot was taken; caps the quantity selector. */
  available: number;
}

export interface CartLine {
  variantId: string;
  quantity: number;
  snapshot: CartSnapshot;
}

interface CartState {
  lines: CartLine[];
  addItem: (variantId: string, snapshot: CartSnapshot, quantity?: number) => void;
  setQuantity: (variantId: string, quantity: number) => void;
  removeItem: (variantId: string) => void;
  /** Replaces the cart with server-validated lines. */
  replaceLines: (lines: CartLine[]) => void;
  clear: () => void;
}

function clampQuantity(quantity: number, available: number): number {
  const max = Math.min(available, CATALOG.maxQuantityPerLine);
  return Math.max(0, Math.min(Math.floor(quantity), max));
}

export const CART_STORAGE_KEY = "northfold-cart";

export const useCartStore = create<CartState>()(
  persist(
    (set) => ({
      lines: [],
      addItem: (variantId, snapshot, quantity = 1) =>
        set((state) => {
          const existing = state.lines.find((line) => line.variantId === variantId);
          const nextQuantity = clampQuantity(
            (existing?.quantity ?? 0) + quantity,
            snapshot.available,
          );
          if (nextQuantity === 0) return state;
          if (!existing)
            return { lines: [...state.lines, { variantId, quantity: nextQuantity, snapshot }] };
          return {
            lines: state.lines.map((line) =>
              line.variantId === variantId ? { ...line, quantity: nextQuantity, snapshot } : line,
            ),
          };
        }),
      setQuantity: (variantId, quantity) =>
        set((state) => ({
          lines: state.lines.flatMap((line) => {
            if (line.variantId !== variantId) return [line];
            const next = clampQuantity(quantity, line.snapshot.available);
            return next === 0 ? [] : [{ ...line, quantity: next }];
          }),
        })),
      removeItem: (variantId) =>
        set((state) => ({ lines: state.lines.filter((line) => line.variantId !== variantId) })),
      replaceLines: (lines) => set({ lines }),
      clear: () => set({ lines: [] }),
    }),
    {
      name: CART_STORAGE_KEY,
      version: 1,
      storage: createJSONStorage(() => localStorage),
      // Rehydrated manually after mount (CartHydrator) so server and first client render match.
      skipHydration: true,
      partialize: (state) => ({ lines: state.lines }),
    },
  ),
);

export function selectItemCount(state: Pick<CartState, "lines">): number {
  return state.lines.reduce((count, line) => count + line.quantity, 0);
}

export function selectTotals(state: Pick<CartState, "lines">): OrderTotals {
  return calculateTotals(
    state.lines.map((line) => ({ unitPrice: line.snapshot.unitPrice, quantity: line.quantity })),
  );
}

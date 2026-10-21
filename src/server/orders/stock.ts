import "server-only";

import type { Prisma } from "@/generated/prisma/client";

export interface StockLine {
  variantId: string;
  quantity: number;
  label: string;
}

/**
 * Conditionally decrements stock for every line (`stock >= quantity`), in a stable order to avoid
 * deadlocks between concurrent transactions. Returns the labels of lines that could not be
 * decremented; callers inside a transaction must roll back when any line fails.
 */
export async function decrementStock(
  tx: Prisma.TransactionClient,
  lines: readonly StockLine[],
): Promise<{ failed: string[] }> {
  const failed: string[] = [];
  const ordered = [...lines].sort((a, b) => a.variantId.localeCompare(b.variantId));
  for (const line of ordered) {
    const { count } = await tx.productVariant.updateMany({
      where: { id: line.variantId, stock: { gte: line.quantity } },
      data: { stock: { decrement: line.quantity } },
    });
    if (count === 0) failed.push(line.label);
  }
  return { failed };
}

/** Puts stock back for lines whose variant still exists. */
export async function restockItems(
  tx: Prisma.TransactionClient,
  lines: readonly { variantId: string | null; quantity: number }[],
): Promise<void> {
  const ordered = [...lines].sort((a, b) => (a.variantId ?? "").localeCompare(b.variantId ?? ""));
  for (const line of ordered) {
    if (!line.variantId) continue;
    await tx.productVariant.updateMany({
      where: { id: line.variantId },
      data: { stock: { increment: line.quantity } },
    });
  }
}

/** Thrown inside a transaction to roll it back when stock ran out. */
export class OutOfStockError extends Error {
  constructor(readonly labels: string[]) {
    super(`Out of stock: ${labels.join(", ")}`);
    this.name = "OutOfStockError";
  }
}

export function outOfStockMessage(labels: readonly string[]): string {
  return `Sorry — ${labels.join(", ")} ${labels.length === 1 ? "is" : "are"} no longer available in the quantity you chose. Please review your bag.`;
}

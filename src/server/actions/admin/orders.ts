"use server";

import { revalidatePath, revalidateTag } from "next/cache";

import { type ActionResult, fail, ok } from "@/lib/action-result";
import { CACHE_TAGS } from "@/lib/cache-tags";
import { orderIdSchema, updateOrderStatusSchema } from "@/lib/validators/order";
import { runAction } from "@/server/action";
import { requireAdmin } from "@/server/auth/session";
import { changeOrderStatus, resolveReview } from "@/server/orders/admin-status";

function refreshOrderViews(orderId: string) {
  revalidatePath("/admin");
  revalidatePath("/admin/orders");
  revalidatePath(`/admin/orders/${orderId}`);
}

export async function updateOrderStatus(input: unknown): Promise<ActionResult> {
  return runAction("admin.updateOrderStatus", async () => {
    await requireAdmin();
    const parsed = updateOrderStatusSchema.safeParse(input);
    if (!parsed.success) return fail("Invalid status change.");
    const { stockChanged } = await changeOrderStatus(parsed.data.orderId, parsed.data.status);
    if (stockChanged) revalidateTag(CACHE_TAGS.products, "max");
    refreshOrderViews(parsed.data.orderId);
    return ok();
  });
}

export async function resolveOrderReview(input: unknown): Promise<ActionResult> {
  return runAction("admin.resolveOrderReview", async () => {
    await requireAdmin();
    const parsed = orderIdSchema.safeParse(input);
    if (!parsed.success) return fail("Order not found.");
    await resolveReview(parsed.data.orderId);
    refreshOrderViews(parsed.data.orderId);
    return ok();
  });
}

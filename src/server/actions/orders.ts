"use server";

import type { OrderStatus, PaymentStatus } from "@/generated/prisma/enums";
import { type ActionResult, fail, ok } from "@/lib/action-result";
import { prisma } from "@/lib/prisma";
import { orderIdSchema } from "@/lib/validators/order";
import { runAction } from "@/server/action";
import { requireUser } from "@/server/auth/session";

/** Lets the confirmation page poll its own order's payment state while Stripe's webhook arrives. */
export async function getOrderPaymentState(
  input: unknown,
): Promise<ActionResult<{ status: OrderStatus; paymentStatus: PaymentStatus }>> {
  return runAction("getOrderPaymentState", async () => {
    const user = await requireUser();
    const parsed = orderIdSchema.safeParse(input);
    if (!parsed.success) return fail("Order not found.");
    const order = await prisma.order.findFirst({
      where: { id: parsed.data.orderId, userId: user.id },
      select: { status: true, paymentStatus: true },
    });
    return order ? ok(order) : fail("Order not found.");
  });
}

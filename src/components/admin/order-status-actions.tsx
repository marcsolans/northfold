"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import toast from "react-hot-toast";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import type { OrderStatus, PaymentMethod, PaymentStatus } from "@/generated/prisma/enums";
import { allowedTransitions } from "@/lib/order-status";
import { resolveOrderReview, updateOrderStatus } from "@/server/actions/admin/orders";

const ACTION_LABELS: Record<OrderStatus, string> = {
  PENDING: "Mark pending",
  PROCESSING: "Start processing",
  SHIPPED: "Mark shipped",
  DELIVERED: "Mark delivered",
  CANCELLED: "Cancel order",
};

/** Buttons for exactly the transitions the state machine allows from the current status. */
export function OrderStatusActions({
  orderId,
  status,
  paymentMethod,
  paymentStatus,
  needsReview,
}: {
  orderId: string;
  status: OrderStatus;
  paymentMethod: PaymentMethod;
  paymentStatus: PaymentStatus;
  needsReview: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [confirmCancel, setConfirmCancel] = useState(false);
  const transitions = allowedTransitions(status);
  const awaitingCardPayment = paymentMethod === "STRIPE" && paymentStatus !== "PAID";

  function run(action: () => Promise<{ ok: boolean; error?: string }>, success: string) {
    startTransition(async () => {
      const result = await action();
      if (!result.ok) {
        toast.error(result.error ?? "Something went wrong.");
        return;
      }
      toast.success(success);
      setConfirmCancel(false);
      router.refresh();
    });
  }

  if (transitions.length === 0 && !needsReview) {
    return (
      <p className="text-sm text-muted-foreground">
        This order is final; no further status changes.
      </p>
    );
  }

  const cancelNote =
    paymentMethod === "STRIPE" && paymentStatus === "PAID"
      ? "The card payment will be refunded through Stripe and the items restocked."
      : "The items will be put back in stock. No payment was taken.";

  return (
    <div className="flex flex-wrap gap-2">
      {transitions
        .filter((to) => to !== "CANCELLED")
        .map((to) => (
          <Button
            key={to}
            size="sm"
            disabled={pending || (to === "PROCESSING" && awaitingCardPayment)}
            title={
              to === "PROCESSING" && awaitingCardPayment
                ? "Waiting for the card payment"
                : undefined
            }
            onClick={() =>
              run(
                () => updateOrderStatus({ orderId, status: to }),
                `Order marked ${to.toLowerCase()}`,
              )
            }
          >
            {ACTION_LABELS[to]}
          </Button>
        ))}
      {transitions.includes("CANCELLED") ? (
        <Button
          size="sm"
          variant="outline"
          disabled={pending}
          onClick={() => setConfirmCancel(true)}
        >
          Cancel order
        </Button>
      ) : null}
      {needsReview ? (
        <Button
          size="sm"
          variant="secondary"
          disabled={pending}
          onClick={() => run(() => resolveOrderReview({ orderId }), "Review flag cleared")}
        >
          Mark review resolved
        </Button>
      ) : null}
      <Modal
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        title="Cancel this order?"
        description={cancelNote}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmCancel(false)} disabled={pending}>
              Keep order
            </Button>
            <Button
              variant="destructive"
              loading={pending}
              loadingText="Cancelling…"
              onClick={() =>
                run(() => updateOrderStatus({ orderId, status: "CANCELLED" }), "Order cancelled")
              }
            >
              Cancel order
            </Button>
          </>
        }
      />
    </div>
  );
}

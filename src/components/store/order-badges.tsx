import { Badge, type BadgeTone } from "@/components/ui/badge";
import type { OrderStatus, PaymentMethod, PaymentStatus } from "@/generated/prisma/enums";

const STATUS: Record<OrderStatus, { label: string; tone: BadgeTone }> = {
  PENDING: { label: "Pending", tone: "warning" },
  PROCESSING: { label: "Processing", tone: "accent" },
  SHIPPED: { label: "Shipped", tone: "accent" },
  DELIVERED: { label: "Delivered", tone: "success" },
  CANCELLED: { label: "Cancelled", tone: "neutral" },
};

const PAYMENT: Record<PaymentStatus, { label: string; tone: BadgeTone }> = {
  PENDING: { label: "Payment pending", tone: "warning" },
  PAID: { label: "Paid", tone: "success" },
  FAILED: { label: "Payment failed", tone: "destructive" },
  REFUNDED: { label: "Refunded", tone: "neutral" },
};

export const PAYMENT_METHOD_LABELS: Record<PaymentMethod, string> = {
  STRIPE: "Card (Stripe)",
  CASH_ON_DELIVERY: "Cash on delivery",
};

export const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  PENDING: STATUS.PENDING.label,
  PROCESSING: STATUS.PROCESSING.label,
  SHIPPED: STATUS.SHIPPED.label,
  DELIVERED: STATUS.DELIVERED.label,
  CANCELLED: STATUS.CANCELLED.label,
};

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  return <Badge tone={STATUS[status].tone}>{STATUS[status].label}</Badge>;
}

/** Payment state; an unpaid order that was cancelled reads "Not charged", not "pending". */
export function PaymentStatusBadge({
  status,
  orderStatus,
}: {
  status: PaymentStatus;
  orderStatus?: OrderStatus;
}) {
  if (orderStatus === "CANCELLED" && status === "PENDING")
    return <Badge tone="neutral">Not charged</Badge>;
  return <Badge tone={PAYMENT[status].tone}>{PAYMENT[status].label}</Badge>;
}

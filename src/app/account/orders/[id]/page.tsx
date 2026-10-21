import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { HiArrowLeft } from "react-icons/hi2";

import { CancelOrderButton } from "@/components/account/cancel-order-button";
import { OrderStatusBadge } from "@/components/store/order-badges";
import { OrderDetails } from "@/components/store/order-details";
import { OrderTimeline } from "@/components/store/order-timeline";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/format";
import { orderNumber } from "@/lib/orders";
import { requireUserPage } from "@/server/auth/session";
import { getOrderForUser } from "@/server/queries/orders";

export const metadata: Metadata = { title: "Order details", robots: { index: false } };

async function OrderDetail({ params }: Pick<PageProps<"/account/orders/[id]">, "params">) {
  const { id } = await params;
  const user = await requireUserPage(`/account/orders/${id}`);
  // Ownership: another customer's order id behaves exactly like a missing one.
  const order = await getOrderForUser(user.id, id);
  if (!order) notFound();

  const cancellable = order.paymentMethod === "CASH_ON_DELIVERY" && order.status === "PENDING";

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-light tracking-tight">{orderNumber(order.id)}</h1>
            <OrderStatusBadge status={order.status} />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Placed {formatDateTime(order.createdAt)}
          </p>
        </div>
        {cancellable ? <CancelOrderButton orderId={order.id} /> : null}
      </div>
      <OrderTimeline order={order} />
      <OrderDetails order={order} />
    </div>
  );
}

export default function AccountOrderPage({ params }: PageProps<"/account/orders/[id]">) {
  return (
    <>
      <Link
        href="/account/orders"
        className="mb-6 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
      >
        <HiArrowLeft aria-hidden="true" className="size-4" />
        All orders
      </Link>
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <OrderDetail params={params} />
      </Suspense>
    </>
  );
}

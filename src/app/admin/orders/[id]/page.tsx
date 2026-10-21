import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { HiArrowLeft, HiOutlineExclamationTriangle } from "react-icons/hi2";

import { AdminPageHeader } from "@/components/admin/admin-shell";
import { OrderStatusActions } from "@/components/admin/order-status-actions";
import { OrderStatusBadge } from "@/components/store/order-badges";
import { OrderDetails } from "@/components/store/order-details";
import { OrderTimeline } from "@/components/store/order-timeline";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/format";
import { orderNumber } from "@/lib/orders";
import { requireAdminPage } from "@/server/auth/session";
import { getAdminOrder } from "@/server/queries/admin";

export const metadata: Metadata = { title: "Order" };

async function AdminOrder({ params }: Pick<PageProps<"/admin/orders/[id]">, "params">) {
  const { id } = await params;
  await requireAdminPage(`/admin/orders/${id}`);
  const order = await getAdminOrder(id);
  if (!order) notFound();

  return (
    <>
      <AdminPageHeader
        title={orderNumber(order.id)}
        description={`Placed ${formatDateTime(order.createdAt)}`}
        actions={<OrderStatusBadge status={order.status} />}
      />
      <div className="space-y-8">
        {order.needsReview ? (
          <div
            role="alert"
            className="flex gap-3 rounded-lg border border-warning/30 bg-warning-soft px-5 py-4 text-sm"
          >
            <HiOutlineExclamationTriangle
              aria-hidden="true"
              className="mt-0.5 size-5 shrink-0 text-warning"
            />
            <div>
              <p className="font-medium">Needs review</p>
              <p className="mt-1 text-muted-foreground">{order.reviewReason}</p>
            </div>
          </div>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>Fulfilment</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <OrderTimeline order={order} />
            <OrderStatusActions
              orderId={order.id}
              status={order.status}
              paymentMethod={order.paymentMethod}
              paymentStatus={order.paymentStatus}
              needsReview={order.needsReview}
            />
          </CardContent>
        </Card>

        <div className="grid gap-6 sm:grid-cols-2">
          <Card className="min-w-0">
            <CardHeader>
              <CardTitle>Customer</CardTitle>
            </CardHeader>
            <CardContent className="text-sm">
              <p className="font-medium">{order.customer.name}</p>
              <a
                href={`mailto:${order.customer.email}`}
                className="break-all text-muted-foreground underline-offset-4 hover:underline"
              >
                {order.customer.email}
              </a>
            </CardContent>
          </Card>
          <Card className="min-w-0">
            <CardHeader>
              <CardTitle>Payment references</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm text-muted-foreground">
              <p>Stock taken: {order.stockDeducted ? "yes" : "no"}</p>
              {order.paidAt ? <p>Paid: {formatDateTime(order.paidAt)}</p> : null}
              {order.stripeSessionId ? (
                <p className="break-all">Session: {order.stripeSessionId}</p>
              ) : null}
              {order.stripePaymentIntentId ? (
                <p className="break-all">Payment intent: {order.stripePaymentIntentId}</p>
              ) : null}
            </CardContent>
          </Card>
        </div>

        <OrderDetails order={order} />
      </div>
    </>
  );
}

export default function AdminOrderPage({ params }: PageProps<"/admin/orders/[id]">) {
  return (
    <>
      <Link
        href="/admin/orders"
        className="mb-6 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
      >
        <HiArrowLeft aria-hidden="true" className="size-4" />
        All orders
      </Link>
      <Suspense fallback={<Skeleton className="h-[32rem] w-full" />}>
        <AdminOrder params={params} />
      </Suspense>
    </>
  );
}

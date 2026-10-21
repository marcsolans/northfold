import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { HiOutlineCheckCircle, HiOutlineExclamationTriangle } from "react-icons/hi2";

import { ClearCart } from "@/components/store/clear-cart";
import { OrderDetails } from "@/components/store/order-details";
import { PaymentStatusPoller } from "@/components/store/payment-status-poller";
import { buttonClasses } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney } from "@/lib/money";
import { orderNumber } from "@/lib/orders";
import { firstParam } from "@/lib/validators/common";
import { requireUserPage } from "@/server/auth/session";
import { getOrderForUser, type OrderDetailDTO } from "@/server/queries/orders";

export const metadata: Metadata = { title: "Order confirmation", robots: { index: false } };

type Outcome = "confirmed" | "paid" | "pending" | "failed";

function outcomeOf(order: OrderDetailDTO): Outcome {
  if (order.paymentMethod === "CASH_ON_DELIVERY")
    return order.status === "CANCELLED" ? "failed" : "confirmed";
  if (order.paymentStatus === "PAID") return "paid";
  if (order.paymentStatus === "PENDING" && order.status === "PENDING") return "pending";
  return "failed";
}

/**
 * Never trusts the URL: the order is loaded from the database (and must belong to the signed-in
 * customer), and its stored payment state decides what is shown.
 */
async function Confirmation({
  searchParams,
}: Pick<PageProps<"/checkout/success">, "searchParams">) {
  const orderId = firstParam((await searchParams).order) ?? "";
  const user = await requireUserPage(`/checkout/success?order=${encodeURIComponent(orderId)}`);
  const order = orderId ? await getOrderForUser(user.id, orderId) : null;
  if (!order) notFound();

  const outcome = outcomeOf(order);
  const confirmed = outcome === "confirmed" || outcome === "paid";

  return (
    <>
      {confirmed ? <ClearCart /> : null}
      <div className="mb-10 rounded-lg border border-border bg-card p-6 sm:p-8">
        <div className="flex items-start gap-4">
          {outcome === "failed" ? (
            <HiOutlineExclamationTriangle
              aria-hidden="true"
              className="size-8 shrink-0 text-destructive"
            />
          ) : (
            <HiOutlineCheckCircle
              aria-hidden="true"
              className={
                confirmed ? "size-8 shrink-0 text-success" : "size-8 shrink-0 text-muted-foreground"
              }
            />
          )}
          <div className="min-w-0">
            <p className="text-sm text-muted-foreground">Order {orderNumber(order.id)}</p>
            <h1 className="mt-1 text-2xl font-light tracking-tight sm:text-3xl">
              {outcome === "confirmed" &&
                `Thank you, ${user.name.split(" ")[0]} — your order is confirmed`}
              {outcome === "paid" && `Thank you, ${user.name.split(" ")[0]} — payment received`}
              {outcome === "pending" && "Almost there"}
              {outcome === "failed" && "Your payment was not completed"}
            </h1>
            <div className="mt-3 text-sm text-muted-foreground">
              {outcome === "confirmed" && (
                <p>
                  Please have {formatMoney(order.total)} ready in cash when your order arrives.
                  We’ll start preparing it right away.
                </p>
              )}
              {outcome === "paid" && (
                <p>We’ve received your payment and are preparing your order.</p>
              )}
              {outcome === "pending" && <PaymentStatusPoller orderId={order.id} />}
              {outcome === "failed" && (
                <p>
                  No payment was taken. Your bag is still saved — you can try again whenever you
                  like.
                </p>
              )}
            </div>
            <div className="mt-6 flex flex-wrap gap-3">
              {outcome === "failed" ? (
                <Link href="/cart" className={buttonClasses()}>
                  Return to your bag
                </Link>
              ) : (
                <Link href={`/account/orders/${order.id}`} className={buttonClasses()}>
                  View order
                </Link>
              )}
              <Link href="/shop" className={buttonClasses({ variant: "outline" })}>
                Continue shopping
              </Link>
            </div>
          </div>
        </div>
      </div>
      <OrderDetails order={order} />
    </>
  );
}

export default function CheckoutSuccessPage({ searchParams }: PageProps<"/checkout/success">) {
  return (
    <div className="mx-auto max-w-6xl px-4 pt-10 pb-16 sm:px-6">
      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <Confirmation searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

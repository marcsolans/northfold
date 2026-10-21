import Image from "next/image";
import Link from "next/link";

import { formatMoney } from "@/lib/money";
import type { OrderDetailDTO } from "@/server/queries/orders";

import { AddressSummary } from "./address-summary";
import { PAYMENT_METHOD_LABELS, PaymentStatusBadge } from "./order-badges";
import { OrderSummary } from "./order-summary";

/** Items, shipping address, payment and totals of an order (all from the order's snapshots). */
export function OrderDetails({
  order,
  linkProducts = true,
}: {
  order: OrderDetailDTO;
  linkProducts?: boolean;
}) {
  return (
    <div className="grid items-start gap-10 lg:grid-cols-[1fr_22rem]">
      <section aria-labelledby="order-items-heading">
        <h2 id="order-items-heading" className="text-base font-medium">
          Items
        </h2>
        <ul className="mt-4 divide-y divide-border border-y border-border">
          {order.items.map((item) => (
            <li key={item.id} className="flex gap-4 py-4">
              <div className="relative aspect-[4/5] w-16 shrink-0 overflow-hidden rounded-md bg-surface">
                {item.imageUrl ? (
                  <Image src={item.imageUrl} alt="" fill sizes="64px" className="object-cover" />
                ) : null}
              </div>
              <div className="min-w-0 flex-1 text-sm">
                <p className="font-medium">
                  {linkProducts ? (
                    <Link href={`/products/${item.productSlug}`} className="hover:underline">
                      {item.productName}
                    </Link>
                  ) : (
                    item.productName
                  )}
                </p>
                <p className="mt-1 text-muted-foreground">
                  Size {item.size} · {item.colorName} · {item.sku}
                </p>
                <p className="mt-1 text-muted-foreground">
                  {item.quantity} × {formatMoney(item.unitPrice)}
                </p>
              </div>
              <p className="text-sm font-medium tabular-nums">{formatMoney(item.lineTotal)}</p>
            </li>
          ))}
        </ul>
        <div className="mt-8 grid gap-8 sm:grid-cols-2">
          <div>
            <h2 className="text-sm font-medium">Shipping address</h2>
            <AddressSummary
              address={order.shippingAddress}
              className="mt-2 text-sm leading-relaxed text-muted-foreground not-italic"
            />
          </div>
          <div>
            <h2 className="text-sm font-medium">Payment</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {PAYMENT_METHOD_LABELS[order.paymentMethod]}
            </p>
            <div className="mt-2">
              <PaymentStatusBadge status={order.paymentStatus} orderStatus={order.status} />
            </div>
          </div>
        </div>
      </section>
      <OrderSummary totals={order} />
    </div>
  );
}

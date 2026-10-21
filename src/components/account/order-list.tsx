import Image from "next/image";
import Link from "next/link";
import { HiChevronRight } from "react-icons/hi2";

import { OrderStatusBadge, PaymentStatusBadge } from "@/components/store/order-badges";
import { formatDate } from "@/lib/format";
import { formatMoney } from "@/lib/money";
import { orderNumber } from "@/lib/orders";
import { pluralize } from "@/lib/utils";
import type { OrderListItemDTO } from "@/server/queries/orders";

export function OrderList({ orders }: { orders: OrderListItemDTO[] }) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border bg-card">
      {orders.map((order) => (
        <li key={order.id}>
          <Link
            href={`/account/orders/${order.id}`}
            className="flex items-center gap-4 px-4 py-4 transition-colors hover:bg-surface/50 sm:px-5"
          >
            <div className="hidden shrink-0 -space-x-3 sm:flex">
              {order.thumbnails.map((src, index) => (
                <span
                  key={`${src}-${index}`}
                  className="relative size-12 overflow-hidden rounded-md border-2 border-card bg-surface"
                >
                  <Image src={src} alt="" fill sizes="48px" className="object-cover" />
                </span>
              ))}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{orderNumber(order.id)}</p>
              <p className="mt-0.5 text-sm text-muted-foreground">
                {formatDate(order.createdAt)} · {pluralize(order.itemCount, "item")} ·{" "}
                {formatMoney(order.total)}
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <OrderStatusBadge status={order.status} />
                <PaymentStatusBadge status={order.paymentStatus} orderStatus={order.status} />
              </div>
            </div>
            <HiChevronRight aria-hidden="true" className="size-5 shrink-0 text-muted-foreground" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

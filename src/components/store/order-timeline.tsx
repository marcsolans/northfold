import { HiCheck, HiXMark } from "react-icons/hi2";

import type { OrderStatus } from "@/generated/prisma/enums";
import { formatDateTime } from "@/lib/format";
import { ORDER_STATUS_FLOW } from "@/lib/order-status";
import { cn } from "@/lib/utils";

import { ORDER_STATUS_LABELS } from "./order-badges";

interface TimelineOrder {
  status: OrderStatus;
  createdAt: string;
  paidAt: string | null;
  shippedAt: string | null;
  deliveredAt: string | null;
  cancelledAt: string | null;
}

/** PENDING → PROCESSING → SHIPPED → DELIVERED, or a cancellation note. */
export function OrderTimeline({ order }: { order: TimelineOrder }) {
  if (order.status === "CANCELLED") {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-5 py-4 text-sm">
        <span className="flex size-8 items-center justify-center rounded-full bg-surface">
          <HiXMark aria-hidden="true" className="size-4" />
        </span>
        <span>Cancelled{order.cancelledAt ? ` on ${formatDateTime(order.cancelledAt)}` : ""}.</span>
      </div>
    );
  }

  const reached = ORDER_STATUS_FLOW.indexOf(order.status);
  const dates: Partial<Record<OrderStatus, string | null>> = {
    PENDING: order.createdAt,
    PROCESSING: order.paidAt,
    SHIPPED: order.shippedAt,
    DELIVERED: order.deliveredAt,
  };

  return (
    <ol className="grid grid-cols-4 gap-2" aria-label="Order progress">
      {ORDER_STATUS_FLOW.map((status, index) => {
        const done = index <= reached;
        const date = dates[status];
        return (
          <li
            key={status}
            className="flex flex-col gap-2"
            aria-current={index === reached ? "step" : undefined}
          >
            <div className="flex items-center">
              <span
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-full border text-xs",
                  done
                    ? "border-accent bg-accent text-accent-foreground"
                    : "border-border bg-card text-muted-foreground",
                )}
              >
                {done ? <HiCheck aria-hidden="true" className="size-4" /> : index + 1}
              </span>
              {index < ORDER_STATUS_FLOW.length - 1 ? (
                <span
                  className={cn("ml-2 h-px flex-1", index < reached ? "bg-accent" : "bg-border")}
                />
              ) : null}
            </div>
            <span
              className={cn("text-xs sm:text-sm", done ? "font-medium" : "text-muted-foreground")}
            >
              {ORDER_STATUS_LABELS[status]}
              <span className="sr-only">{done ? " (done)" : " (upcoming)"}</span>
            </span>
            {done && date ? (
              <span className="hidden text-xs text-muted-foreground sm:block">
                {formatDateTime(date)}
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

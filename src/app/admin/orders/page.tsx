import type { Metadata } from "next";
import Form from "next/form";
import Link from "next/link";
import { Suspense } from "react";
import { HiOutlineClipboardDocumentList, HiOutlineExclamationTriangle } from "react-icons/hi2";

import { AdminPageHeader } from "@/components/admin/admin-shell";
import {
  ORDER_STATUS_LABELS,
  OrderStatusBadge,
  PAYMENT_METHOD_LABELS,
  PaymentStatusBadge,
} from "@/components/store/order-badges";
import { buttonClasses } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Pagination } from "@/components/ui/pagination";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { OrderStatus, PaymentMethod } from "@/generated/prisma/enums";
import { formatDate } from "@/lib/format";
import { formatMoney } from "@/lib/money";
import { orderNumber } from "@/lib/orders";
import { firstParam } from "@/lib/validators/common";
import { type AdminOrderFilters, parseAdminOrderFilters } from "@/lib/validators/order";
import { listAdminOrders } from "@/server/queries/admin";

export const metadata: Metadata = { title: "Orders" };

function hrefFor(filters: AdminOrderFilters & { review: boolean }, page: number) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.payment) params.set("payment", filters.payment);
  if (filters.review) params.set("review", "1");
  if (filters.q) params.set("q", filters.q);
  if (page > 1) params.set("page", String(page));
  const query = params.toString();
  return query ? `/admin/orders?${query}` : "/admin/orders";
}

async function Orders({ searchParams }: Pick<PageProps<"/admin/orders">, "searchParams">) {
  const params = await searchParams;
  const filters = { ...parseAdminOrderFilters(params), review: firstParam(params.review) === "1" };
  const result = await listAdminOrders(filters);

  return (
    <>
      <Form
        action="/admin/orders"
        className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_12rem_12rem_auto_auto]"
      >
        <label htmlFor="order-search" className="sr-only">
          Search orders
        </label>
        <Input
          id="order-search"
          name="q"
          defaultValue={filters.q}
          placeholder="Order number, email or name"
        />
        <Select
          name="status"
          aria-label="Filter by status"
          defaultValue={filters.status ?? ""}
          placeholder="All statuses"
          options={Object.values(OrderStatus).map((value) => ({
            value,
            label: ORDER_STATUS_LABELS[value],
          }))}
        />
        <Select
          name="payment"
          aria-label="Filter by payment method"
          defaultValue={filters.payment ?? ""}
          placeholder="All payment methods"
          options={Object.values(PaymentMethod).map((value) => ({
            value,
            label: PAYMENT_METHOD_LABELS[value],
          }))}
        />
        <label className="flex h-11 items-center gap-2 text-sm">
          <input
            type="checkbox"
            name="review"
            value="1"
            defaultChecked={filters.review}
            className="size-4 accent-accent"
          />
          Needs review
        </label>
        <button type="submit" className={buttonClasses({ variant: "outline" })}>
          Filter
        </button>
      </Form>

      {result.total === 0 ? (
        <EmptyState
          icon={<HiOutlineClipboardDocumentList />}
          title="No orders found"
          description="Try different filters."
          action={
            <Link href="/admin/orders" className={buttonClasses({ variant: "outline" })}>
              Clear filters
            </Link>
          }
        />
      ) : (
        <>
          <Table>
            <TableHead>
              <tr>
                <TableHeaderCell>Order</TableHeaderCell>
                <TableHeaderCell>Customer</TableHeaderCell>
                <TableHeaderCell>Payment</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell className="text-right">Total</TableHeaderCell>
              </tr>
            </TableHead>
            <TableBody>
              {result.orders.map((order) => (
                <TableRow key={order.id}>
                  <TableCell>
                    <Link
                      href={`/admin/orders/${order.id}`}
                      className="inline-flex items-center gap-1.5 font-medium hover:underline"
                    >
                      {order.needsReview ? (
                        <HiOutlineExclamationTriangle
                          aria-label="Needs review"
                          className="size-4 text-warning"
                        />
                      ) : null}
                      {orderNumber(order.id)}
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      {formatDate(order.createdAt)} · {order.itemCount} items
                    </p>
                  </TableCell>
                  <TableCell>
                    {order.customerName}
                    <p className="text-xs text-muted-foreground">{order.customerEmail}</p>
                  </TableCell>
                  <TableCell>
                    <p className="mb-1 text-xs text-muted-foreground">
                      {PAYMENT_METHOD_LABELS[order.paymentMethod]}
                    </p>
                    <PaymentStatusBadge status={order.paymentStatus} orderStatus={order.status} />
                  </TableCell>
                  <TableCell>
                    <OrderStatusBadge status={order.status} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(order.total)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Pagination
            className="mt-8"
            page={result.page}
            totalPages={result.totalPages}
            hrefForPage={(page) => hrefFor(filters, page)}
          />
        </>
      )}
    </>
  );
}

export default function AdminOrdersPage({ searchParams }: PageProps<"/admin/orders">) {
  return (
    <>
      <AdminPageHeader
        title="Orders"
        description="Filter, review and move orders through fulfilment."
      />
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <Orders searchParams={searchParams} />
      </Suspense>
    </>
  );
}

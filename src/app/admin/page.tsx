import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { HiOutlineExclamationTriangle } from "react-icons/hi2";

import { AdminPageHeader } from "@/components/admin/admin-shell";
import { RevenueChart } from "@/components/admin/revenue-chart";
import { StatCard } from "@/components/admin/stat-card";
import { OrderStatusBadge, PAYMENT_METHOD_LABELS } from "@/components/store/order-badges";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { OrderStatus } from "@/generated/prisma/enums";
import { formatDate } from "@/lib/format";
import { formatMoney } from "@/lib/money";
import { orderNumber } from "@/lib/orders";
import { pluralize } from "@/lib/utils";
import { getDashboardStats } from "@/server/queries/admin";

export const metadata: Metadata = { title: "Overview" };

async function Overview() {
  const stats = await getDashboardStats();

  return (
    <div className="space-y-8">
      {stats.needsReview > 0 ? (
        <Link
          href="/admin/orders?review=1"
          className="flex items-center gap-3 rounded-lg border border-warning/30 bg-warning-soft px-5 py-4 text-sm"
        >
          <HiOutlineExclamationTriangle aria-hidden="true" className="size-5 text-warning" />
          <span>
            <strong className="font-medium">{pluralize(stats.needsReview, "order")}</strong> need
            {stats.needsReview === 1 ? "s" : ""} your review (e.g. paid but out of stock).
          </span>
        </Link>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Revenue today"
          value={formatMoney(stats.revenue.today)}
          hint={pluralize(stats.paidOrders.today, "paid order")}
        />
        <StatCard
          label="Last 30 days"
          value={formatMoney(stats.revenue.last30Days)}
          hint={pluralize(stats.paidOrders.last30Days, "paid order")}
        />
        <StatCard
          label="All time"
          value={formatMoney(stats.revenue.allTime)}
          hint={pluralize(stats.paidOrders.allTime, "paid order")}
        />
        <StatCard
          label="Customers"
          value={stats.customers}
          hint="Accounts with the customer role"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Revenue, last 30 days</CardTitle>
          </CardHeader>
          <CardContent>
            <RevenueChart data={stats.revenueSeries} />
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Orders by status</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-border">
              {Object.values(OrderStatus).map((status) => (
                <li key={status}>
                  <Link
                    href={`/admin/orders?status=${status}`}
                    className="flex items-center justify-between py-3 text-sm hover:text-accent"
                  >
                    <OrderStatusBadge status={status} />
                    <span className="tabular-nums">{stats.ordersByStatus[status]}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <section aria-labelledby="recent-orders" className="min-w-0">
          <div className="mb-3 flex items-center justify-between">
            <h2 id="recent-orders" className="text-base font-medium">
              Recent orders
            </h2>
            <Link href="/admin/orders" className="text-sm underline underline-offset-4">
              All orders
            </Link>
          </div>
          <Table>
            <TableHead>
              <tr>
                <TableHeaderCell>Order</TableHeaderCell>
                <TableHeaderCell>Customer</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell className="text-right">Total</TableHeaderCell>
              </tr>
            </TableHead>
            <TableBody>
              {stats.recentOrders.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    No orders yet.
                  </TableCell>
                </TableRow>
              ) : (
                stats.recentOrders.map((order) => (
                  <TableRow key={order.id}>
                    <TableCell>
                      <Link
                        href={`/admin/orders/${order.id}`}
                        className="font-medium hover:underline"
                      >
                        {orderNumber(order.id)}
                      </Link>
                      <p className="text-xs text-muted-foreground">
                        {formatDate(order.createdAt)} · {PAYMENT_METHOD_LABELS[order.paymentMethod]}
                      </p>
                    </TableCell>
                    <TableCell>{order.customer}</TableCell>
                    <TableCell>
                      <OrderStatusBadge status={order.status} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(order.total)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </section>

        <section aria-labelledby="low-stock" className="min-w-0">
          <h2 id="low-stock" className="mb-3 text-base font-medium">
            Low stock (≤ 5)
          </h2>
          <Table>
            <TableHead>
              <tr>
                <TableHeaderCell>Product</TableHeaderCell>
                <TableHeaderCell>Variant</TableHeaderCell>
                <TableHeaderCell className="text-right">Stock</TableHeaderCell>
              </tr>
            </TableHead>
            <TableBody>
              {stats.lowStock.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={3} className="text-muted-foreground">
                    Everything is well stocked.
                  </TableCell>
                </TableRow>
              ) : (
                stats.lowStock.map((variant) => (
                  <TableRow key={variant.variantId}>
                    <TableCell>
                      <Link
                        href={`/admin/products/${variant.productId}/edit`}
                        className="hover:underline"
                      >
                        {variant.productName}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {variant.size} · {variant.colorName}
                      <span className="block text-xs">{variant.sku}</span>
                    </TableCell>
                    <TableCell className="text-right">
                      <Badge tone={variant.stock === 0 ? "destructive" : "warning"}>
                        {variant.stock === 0 ? "Sold out" : `${variant.stock} left`}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </section>
      </div>
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div aria-busy="true" className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
      <Skeleton className="h-80" />
    </div>
  );
}

export default function AdminOverviewPage() {
  return (
    <>
      <AdminPageHeader
        title="Overview"
        description="Revenue counts paid orders, by payment date (UTC)."
      />
      <Suspense fallback={<OverviewSkeleton />}>
        <Overview />
      </Suspense>
    </>
  );
}

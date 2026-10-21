import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { HiOutlineShoppingBag } from "react-icons/hi2";

import { OrderList } from "@/components/account/order-list";
import { AddressSummary } from "@/components/store/address-summary";
import { buttonClasses } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { requireUserPage } from "@/server/auth/session";
import { getUserAddresses } from "@/server/queries/addresses";
import { listOrdersForUser } from "@/server/queries/orders";

export const metadata: Metadata = { title: "Your account", robots: { index: false } };

async function Overview() {
  const user = await requireUserPage("/account");
  const [{ orders, total }, addresses] = await Promise.all([
    listOrdersForUser(user.id, 1, 3),
    getUserAddresses(user.id),
  ]);
  const defaultAddress = addresses.find((address) => address.isDefault);

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-light tracking-tight">Hello, {user.name.split(" ")[0]}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{user.email}</p>
        </div>
        {user.role === "ADMIN" ? (
          <Link href="/admin" className={buttonClasses({ variant: "outline", size: "sm" })}>
            Admin dashboard
          </Link>
        ) : null}
      </div>

      <section aria-labelledby="recent-orders-heading">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="recent-orders-heading" className="text-lg font-medium">
            Recent orders
          </h2>
          {total > orders.length ? (
            <Link href="/account/orders" className="text-sm underline underline-offset-4">
              View all ({total})
            </Link>
          ) : null}
        </div>
        {orders.length > 0 ? (
          <OrderList orders={orders} />
        ) : (
          <EmptyState
            icon={<HiOutlineShoppingBag />}
            title="No orders yet"
            description="When you place an order, it will appear here."
            action={
              <Link href="/shop" className={buttonClasses()}>
                Start shopping
              </Link>
            }
          />
        )}
      </section>

      <div className="grid gap-6 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Default address</CardTitle>
          </CardHeader>
          <CardContent>
            {defaultAddress ? (
              <AddressSummary address={defaultAddress} />
            ) : (
              <p className="text-sm text-muted-foreground">No saved address yet.</p>
            )}
            <Link
              href="/account/addresses"
              className="mt-4 inline-block text-sm underline underline-offset-4"
            >
              Manage addresses
            </Link>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{user.name}</p>
            <p className="text-sm text-muted-foreground">{user.email}</p>
            <Link
              href="/account/profile"
              className="mt-4 inline-block text-sm underline underline-offset-4"
            >
              Edit profile
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default function AccountPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <Overview />
    </Suspense>
  );
}

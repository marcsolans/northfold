import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { HiOutlineShoppingBag } from "react-icons/hi2";

import { OrderList } from "@/components/account/order-list";
import { buttonClasses } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { firstParam, pageSchema } from "@/lib/validators/common";
import { requireUserPage } from "@/server/auth/session";
import { listOrdersForUser } from "@/server/queries/orders";

export const metadata: Metadata = { title: "Your orders", robots: { index: false } };

async function Orders({ searchParams }: Pick<PageProps<"/account/orders">, "searchParams">) {
  const page = pageSchema.parse(firstParam((await searchParams).page));
  const user = await requireUserPage("/account/orders");
  const result = await listOrdersForUser(user.id, page);

  if (result.total === 0) {
    return (
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
    );
  }

  return (
    <>
      <OrderList orders={result.orders} />
      <Pagination
        className="mt-8"
        page={result.page}
        totalPages={result.totalPages}
        hrefForPage={(p) => (p > 1 ? `/account/orders?page=${p}` : "/account/orders")}
      />
    </>
  );
}

export default function AccountOrdersPage({ searchParams }: PageProps<"/account/orders">) {
  return (
    <>
      <h1 className="mb-6 text-3xl font-light tracking-tight">Orders</h1>
      <Suspense fallback={<Skeleton className="h-80 w-full" />}>
        <Orders searchParams={searchParams} />
      </Suspense>
    </>
  );
}

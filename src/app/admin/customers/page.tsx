import type { Metadata } from "next";
import Form from "next/form";
import { Suspense } from "react";
import { HiOutlineUsers } from "react-icons/hi2";

import { AdminPageHeader } from "@/components/admin/admin-shell";
import { Badge } from "@/components/ui/badge";
import { buttonClasses } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { formatDate } from "@/lib/format";
import { formatMoney } from "@/lib/money";
import { firstParam, pageSchema } from "@/lib/validators/common";
import { listCustomers } from "@/server/queries/admin";

export const metadata: Metadata = { title: "Customers" };

async function Customers({ searchParams }: Pick<PageProps<"/admin/customers">, "searchParams">) {
  const params = await searchParams;
  const q = firstParam(params.q)?.trim().slice(0, 100) || undefined;
  const page = pageSchema.parse(firstParam(params.page));
  const result = await listCustomers({ q, page });
  const hrefFor = (p: number) => {
    const query = new URLSearchParams();
    if (q) query.set("q", q);
    if (p > 1) query.set("page", String(p));
    const qs = query.toString();
    return qs ? `/admin/customers?${qs}` : "/admin/customers";
  };

  return (
    <>
      <Form action="/admin/customers" role="search" className="mb-6 flex gap-2">
        <label htmlFor="customer-search" className="sr-only">
          Search customers
        </label>
        <Input
          id="customer-search"
          name="q"
          defaultValue={q}
          placeholder="Name or email"
          className="max-w-sm"
        />
        <button type="submit" className={buttonClasses({ variant: "outline" })}>
          Search
        </button>
      </Form>
      {result.total === 0 ? (
        <EmptyState icon={<HiOutlineUsers />} title="No customers found" />
      ) : (
        <>
          <Table>
            <TableHead>
              <tr>
                <TableHeaderCell>Customer</TableHeaderCell>
                <TableHeaderCell>Joined</TableHeaderCell>
                <TableHeaderCell className="text-right">Orders</TableHeaderCell>
                <TableHeaderCell className="text-right">Total spent</TableHeaderCell>
              </tr>
            </TableHead>
            <TableBody>
              {result.customers.map((customer) => (
                <TableRow key={customer.id}>
                  <TableCell>
                    <span className="font-medium">{customer.name}</span>
                    {customer.role === "ADMIN" ? (
                      <Badge tone="accent" className="ml-2">
                        Admin
                      </Badge>
                    ) : null}
                    <p className="text-xs text-muted-foreground">{customer.email}</p>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(customer.joinedAt)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{customer.orderCount}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(customer.totalSpent)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Pagination
            className="mt-8"
            page={result.page}
            totalPages={result.totalPages}
            hrefForPage={hrefFor}
          />
        </>
      )}
    </>
  );
}

export default function AdminCustomersPage({ searchParams }: PageProps<"/admin/customers">) {
  return (
    <>
      <AdminPageHeader title="Customers" description="Total spent counts paid orders only." />
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <Customers searchParams={searchParams} />
      </Suspense>
    </>
  );
}

import type { Metadata } from "next";
import { Suspense } from "react";

import { AddressBook } from "@/components/account/address-book";
import { Skeleton } from "@/components/ui/skeleton";
import { requireUserPage } from "@/server/auth/session";
import { getUserAddresses } from "@/server/queries/addresses";

export const metadata: Metadata = { title: "Addresses", robots: { index: false } };

async function Addresses() {
  const user = await requireUserPage("/account/addresses");
  return <AddressBook addresses={await getUserAddresses(user.id)} />;
}

export default function AddressesPage() {
  return (
    <Suspense fallback={<Skeleton className="h-80 w-full" />}>
      <Addresses />
    </Suspense>
  );
}

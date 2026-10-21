"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const ITEMS = [
  { href: "/account", label: "Overview" },
  { href: "/account/orders", label: "Orders" },
  { href: "/account/addresses", label: "Addresses" },
  { href: "/account/profile", label: "Profile" },
] as const;

function isActive(pathname: string | null, href: string) {
  if (!pathname) return false;
  return href === "/account" ? pathname === "/account" : pathname.startsWith(href);
}

export function AccountNav() {
  return <AccountNavList pathname={usePathname()} />;
}

export function AccountNavList({ pathname = null }: { pathname?: string | null }) {
  return (
    <nav aria-label="Account">
      <ul className="flex gap-1 overflow-x-auto lg:flex-col">
        {ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <li key={item.href} className="shrink-0">
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "block rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-surface hover:text-foreground",
                )}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

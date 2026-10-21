"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type IconType } from "react-icons";
import {
  HiOutlineClipboardDocumentList,
  HiOutlineCube,
  HiOutlineSquares2X2,
  HiOutlineUsers,
} from "react-icons/hi2";

import { cn } from "@/lib/utils";

const ITEMS: { href: string; label: string; icon: IconType }[] = [
  { href: "/admin", label: "Overview", icon: HiOutlineSquares2X2 },
  { href: "/admin/products", label: "Products", icon: HiOutlineCube },
  { href: "/admin/orders", label: "Orders", icon: HiOutlineClipboardDocumentList },
  { href: "/admin/customers", label: "Customers", icon: HiOutlineUsers },
];

function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  return href === "/admin" ? pathname === "/admin" : pathname.startsWith(href);
}

/** Admin navigation; vertical in the sidebar, horizontal (scrollable) on small screens. */
export function AdminNav({ orientation }: { orientation: "vertical" | "horizontal" }) {
  const pathname = usePathname();
  return <AdminNavList orientation={orientation} pathname={pathname} />;
}

/** Static variant without active state, used as the Suspense fallback. */
export function AdminNavList({
  orientation,
  pathname = null,
}: {
  orientation: "vertical" | "horizontal";
  pathname?: string | null;
}) {
  const vertical = orientation === "vertical";
  return (
    <nav aria-label="Admin">
      <ul className={cn(vertical ? "space-y-1" : "flex gap-1 overflow-x-auto")}>
        {ITEMS.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <li key={href} className="shrink-0">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-surface hover:text-foreground",
                )}
              >
                <Icon aria-hidden="true" className="size-5 shrink-0" />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

import Link from "next/link";
import { HiOutlineUser } from "react-icons/hi2";

import { STORE_NAV } from "@/lib/navigation";
import { PRICING } from "@/lib/store-config";
import { formatMoney } from "@/lib/money";

import { CartButton } from "./cart-button";
import { Logo } from "./logo";
import { MobileMenu } from "./mobile-menu";
import { SearchForm } from "./search-form";

export function Navbar() {
  return (
    <>
      <div className="bg-primary px-4 py-2 text-center text-xs tracking-wide text-primary-foreground">
        Free shipping on orders over {formatMoney(PRICING.freeShippingThreshold, { whole: true })}
      </div>
      <header className="sticky top-0 z-40 border-b border-border bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/75">
        <div className="mx-auto grid h-16 max-w-7xl grid-cols-[1fr_auto_1fr] items-center gap-4 px-4 sm:px-6 lg:grid-cols-[auto_1fr_auto] lg:gap-10">
          <div className="flex items-center lg:hidden">
            <MobileMenu />
          </div>
          <Logo className="justify-self-center lg:justify-self-start" />
          <nav aria-label="Main" className="hidden lg:block">
            <ul className="flex items-center gap-8">
              {STORE_NAV.map((item) => (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className="text-sm tracking-wide text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className="flex items-center justify-end gap-1">
            <SearchForm className="mr-2 hidden w-56 lg:block" />
            <Link
              href="/account"
              aria-label="Your account"
              className="hidden size-10 items-center justify-center rounded-full transition-colors hover:bg-surface sm:inline-flex"
            >
              <HiOutlineUser aria-hidden="true" className="size-[1.375rem]" />
            </Link>
            <CartButton />
          </div>
        </div>
      </header>
    </>
  );
}

import { cacheLife } from "next/cache";
import Link from "next/link";

import { formatMoney } from "@/lib/money";
import { STORE_NAV } from "@/lib/navigation";
import { PRICING, STORE } from "@/lib/store-config";

import { Logo } from "./logo";

/** Cached so the prerendered shell carries the current year without reading the clock per request. */
async function CopyrightYear() {
  "use cache";
  cacheLife("days");
  return <>{new Date().getFullYear()}</>;
}

const HELP_LINKS = [
  { href: "/account", label: "Your account" },
  { href: "/account/orders", label: "Order history" },
  { href: "/cart", label: "Shopping bag" },
] as const;

export function Footer() {
  return (
    <footer className="mt-24 border-t border-border bg-surface/60">
      <div className="mx-auto grid max-w-7xl grid-cols-2 gap-x-6 gap-y-10 px-4 py-14 sm:px-6 md:grid-cols-[2fr_1fr_1fr_1.5fr] md:gap-12">
        <div className="col-span-2 max-w-xs md:col-span-1">
          <Logo />
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground">{STORE.tagline}.</p>
        </div>
        <nav aria-label="Shop">
          <h2 className="text-xs font-medium tracking-[0.2em] uppercase">Shop</h2>
          <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
            {STORE_NAV.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="hover:text-foreground">
                  {item.label === "Shop" ? "All products" : item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <nav aria-label="Help">
          <h2 className="text-xs font-medium tracking-[0.2em] uppercase">Help</h2>
          <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
            {HELP_LINKS.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="hover:text-foreground">
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="col-span-2 md:col-span-1">
          <h2 className="text-xs font-medium tracking-[0.2em] uppercase">Good to know</h2>
          <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
            <li>
              Free shipping on orders over{" "}
              {formatMoney(PRICING.freeShippingThreshold, { whole: true })}
            </li>
            <li>Card payments by Stripe, or cash on delivery</li>
            <li>
              Questions?{" "}
              <a
                href={`mailto:${STORE.supportEmail}`}
                className="underline underline-offset-4 hover:text-foreground"
              >
                {STORE.supportEmail}
              </a>
            </li>
          </ul>
        </div>
      </div>
      <div className="border-t border-border">
        <p className="mx-auto max-w-7xl px-4 py-6 text-xs text-muted-foreground sm:px-6">
          © <CopyrightYear /> {STORE.name}. All rights reserved.
        </p>
      </div>
    </footer>
  );
}

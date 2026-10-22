"use client";

import { Button, cn } from "@messer/ui";
import { Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

export interface NavLink {
  href: string;
  label: string;
}

interface Labels {
  primary: string;
  openMenu: string;
  closeMenu: string;
  login: string;
  cta: string;
}

function isActive(pathname: string, href: string): boolean {
  if (href.includes("#")) return false;
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Desktop links with the current page marked, and the mobile menu (closes on navigation and Escape). */
export function MarketingNav({ links, labels }: { links: NavLink[]; labels: Labels }) {
  const pathname = usePathname();
  // The menu belongs to the page it was opened on, so it closes by itself after a navigation.
  const [openOn, setOpenOn] = React.useState<string | null>(null);
  const open = openOn === pathname;
  const setOpen = React.useCallback((value: boolean) => setOpenOn(value ? pathname : null), [pathname]);
  const panelId = React.useId();

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  return (
    <>
      <nav aria-label={labels.primary} className="hidden md:block">
        <ul className="flex items-center gap-1">
          {links.map((link) => {
            const active = isActive(pathname, link.href);
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "rounded-md px-2.5 py-1.5 text-sm transition-colors hover:bg-subtle hover:text-fg",
                    active ? "font-medium text-fg" : "text-fg-muted",
                  )}
                >
                  {link.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="md:hidden">
        <Button
          variant="ghost"
          size="icon"
          aria-expanded={open}
          aria-controls={panelId}
          aria-label={open ? labels.closeMenu : labels.openMenu}
          onClick={() => setOpen(!open)}
        >
          {open ? <X /> : <Menu />}
        </Button>
        {open ? (
          <div
            id={panelId}
            className="fixed inset-x-0 top-14 bottom-0 z-40 overflow-y-auto border-t border-border bg-bg px-4 pb-8 pt-3"
          >
            <nav aria-label={labels.primary}>
              <ul className="flex flex-col">
                {links.map((link) => (
                  <li key={link.href} className="border-b border-border">
                    <Link
                      href={link.href}
                      onClick={() => setOpen(false)}
                      aria-current={isActive(pathname, link.href) ? "page" : undefined}
                      className="block py-3 text-base text-fg"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
            <div className="mt-6 grid gap-2">
              <Button asChild variant="primary" size="lg">
                <Link href="/signup">{labels.cta}</Link>
              </Button>
              <Button asChild variant="secondary" size="lg">
                <Link href="/login">{labels.login}</Link>
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}

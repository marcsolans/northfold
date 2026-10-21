"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { HiBars3, HiOutlineUser, HiXMark } from "react-icons/hi2";

import { STORE_NAV } from "@/lib/navigation";

import { Logo } from "./logo";
import { SearchForm } from "./search-form";

/**
 * Off-canvas navigation for small screens. The native modal <dialog> traps focus, makes the
 * page inert, closes on Escape and returns focus to the toggle.
 */
export function MobileMenu() {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const dialogId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  // Routes stay mounted (hidden) after client navigation. A modal dialog lives in the top layer,
  // so it must be closed explicitly when this route is hidden or unmounted.
  useEffect(() => {
    const dialog = dialogRef.current;
    return () => {
      dialog?.close();
      setOpen(false);
    };
  }, []);

  const close = () => setOpen(false);

  return (
    <>
      <button
        type="button"
        className="inline-flex size-10 items-center justify-center rounded-full hover:bg-surface lg:hidden"
        aria-label="Open menu"
        aria-expanded={open}
        aria-controls={dialogId}
        onClick={() => setOpen(true)}
      >
        <HiBars3 aria-hidden="true" className="size-6" />
      </button>
      <dialog
        ref={dialogRef}
        id={dialogId}
        aria-label="Menu"
        onClose={close}
        onClick={(event) => {
          if (event.target === event.currentTarget) close();
        }}
        className="m-0 h-dvh max-h-dvh w-[min(22rem,88vw)] max-w-none bg-background p-0 text-foreground backdrop:bg-foreground/40 open:animate-slide-in-left"
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <Logo />
            <button
              type="button"
              onClick={close}
              aria-label="Close menu"
              className="inline-flex size-10 items-center justify-center rounded-full hover:bg-surface"
            >
              <HiXMark aria-hidden="true" className="size-6" />
            </button>
          </div>
          <div className="px-5 pt-5">
            <SearchForm id="mobile-search" />
          </div>
          <nav aria-label="Main" className="flex-1 overflow-y-auto px-5 py-4">
            <ul className="divide-y divide-border">
              {STORE_NAV.map((item) => (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onNavigate={close}
                    className="block py-4 text-lg font-light tracking-tight"
                  >
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className="border-t border-border px-5 py-5">
            <Link
              href="/account"
              onNavigate={close}
              className="flex items-center gap-3 text-sm font-medium"
            >
              <HiOutlineUser aria-hidden="true" className="size-5" />
              Your account
            </Link>
          </div>
        </div>
      </dialog>
    </>
  );
}

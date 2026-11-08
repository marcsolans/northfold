"use client";

import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { usePathname, useRouter } from "@/i18n/navigation";
import { localeNames, locales, type Locale } from "@/i18n/routing";

type Props = {
  locale: Locale;
  label: string;
  /** "down" opens below the trigger (header), "up" above it (footer). */
  placement?: "down" | "up";
  /** "short" shows EN/ES… on the trigger (header), "name" shows English/Español… (footer). */
  variant?: "short" | "name";
  className?: string;
};

function Check() {
  return (
    <svg aria-hidden="true" width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="#b06a38" strokeWidth="1.4">
      <path d="M1.5 5.2 4 7.5l4.5-5" />
    </svg>
  );
}

/** Square listbox language selector; ✓ on the active locale; closes on outside click and Escape. */
export function LanguageSelect({ locale, label, placement = "down", variant = "short", className = "" }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const listId = useId();
  const router = useRouter();
  const pathname = usePathname();

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    optionRefs.current[locales.indexOf(locale)]?.focus();
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) close(false);
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") close(true);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, locale, close]);

  const pick = (next: Locale) => {
    close(true);
    if (next !== locale) router.replace(pathname, { locale: next, scroll: false });
  };

  const onListKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = optionRefs.current.findIndex((el) => el === document.activeElement);
    const focus = (n: number) => optionRefs.current[(n + locales.length) % locales.length]?.focus();
    if (e.key === "ArrowDown") (e.preventDefault(), focus(i + 1));
    else if (e.key === "ArrowUp") (e.preventDefault(), focus(i - 1));
    else if (e.key === "Home") (e.preventDefault(), focus(0));
    else if (e.key === "End") (e.preventDefault(), focus(locales.length - 1));
    else if (e.key === "Tab") close(false);
  };

  const current = localeNames[locale];
  const up = placement === "up";
  // Chevron points down when the list opens downward, up when it opens upward.
  const chevron = up ? (open ? 0 : 180) : open ? 180 : 0;

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={`${label}: ${current.name}`}
        onClick={() => setOpen((o) => !o)}
        className={`inline-flex h-11 items-center gap-2 border border-stone bg-transparent px-3 text-carbon ${
          variant === "short" ? "font-mono text-[11px] uppercase tracking-[0.04em]" : "text-xs"
        }`}
      >
        <span>{variant === "short" ? current.short : current.name}</span>
        <svg
          aria-hidden="true"
          width="8"
          height="8"
          viewBox="0 0 10 10"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.2"
          className="transition-transform duration-300 ease-brand"
          style={{ transform: `rotate(${chevron}deg)` }}
        >
          <path d="M1.5 3.5 5 7l3.5-3.5" />
        </svg>
      </button>
      {open && (
        <div
          id={listId}
          role="listbox"
          aria-label={label}
          onKeyDown={onListKey}
          className={`absolute end-0 z-10 flex w-[190px] flex-col border border-[var(--line-60)] bg-hull p-1 shadow-pop ${
            up ? "bottom-12 animate-[k-menu-up_.2s_var(--ease-brand)_both]" : "top-12 animate-[k-menu_.2s_var(--ease-brand)_both]"
          }`}
        >
          {locales.map((code, i) => {
            const active = code === locale;
            return (
              <button
                key={code}
                ref={(el) => {
                  optionRefs.current[i] = el;
                }}
                type="button"
                role="option"
                aria-selected={active}
                tabIndex={active ? 0 : -1}
                onClick={() => pick(code)}
                className={`flex min-h-11 items-center justify-between gap-3 px-2.5 text-start text-[13px] text-obsidian transition-colors duration-200 hover:bg-signal ${
                  active ? "bg-signal" : "bg-transparent"
                }`}
              >
                <span lang={code}>{localeNames[code].name}</span>
                <span className="inline-flex items-center gap-2 font-mono text-[10px] tracking-[0.08em] text-concrete-deep">
                  {variant === "short" && localeNames[code].short}
                  <span className="inline-flex size-2.5">{active && <Check />}</span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

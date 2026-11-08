"use client";

import { useEffect, useId, useState } from "react";
import { Link } from "@/i18n/navigation";
import { localeNames, locales, type Locale } from "@/i18n/routing";
import { ArrowBox } from "@/components/ui/primitives";
import { LanguageSelect } from "@/components/ui/LanguageSelect";

export type NavLink = { href: string; label: string };

type Props = {
  locale: Locale;
  links: NavLink[];
  cta: NavLink;
  labels: { language: string; openMenu: string; closeMenu: string; home: string; mainNav: string };
};

/** Main nav: logo, links with underline wipe + hover-dim, language listbox, CTA; hamburger panel under 1024px. */
export function NavBar({ locale, links, cta, labels }: Props) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const mq = window.matchMedia("(min-width: 1024px)");
    const onMq = () => mq.matches && setOpen(false);
    document.addEventListener("keydown", onKey);
    mq.addEventListener("change", onMq);
    return () => {
      document.removeEventListener("keydown", onKey);
      mq.removeEventListener("change", onMq);
    };
  }, [open]);

  return (
    <nav
      aria-label={labels.mainNav}
      className="border-b border-[var(--line)] backdrop-blur-[10px]"
      style={{ background: "linear-gradient(rgba(255,255,255,0.96), rgba(255,255,255,0.75))" }}
    >
      <div className="shell flex h-[68px] items-center justify-between gap-6">
        <div className="flex min-w-0 items-center gap-12">
          <a
            href="#top"
            aria-label={labels.home}
            className="inline-flex min-h-11 items-center gap-2 text-[22px] tracking-[-0.05em] text-obsidian"
          >
            <span aria-hidden="true" className="size-[9px] bg-obsidian" />
            Kofen
          </a>
          <div className="hover-dim hidden gap-8 text-[11px] uppercase tracking-[0.12em] lg:flex">
            {links.map((l) => (
              <a key={l.href} href={l.href} className="inline-flex min-h-11 items-center text-carbon">
                <span className="ul">{l.label}</span>
              </a>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2.5">
          <LanguageSelect locale={locale} label={labels.language} className="hidden sm:block" />
          <a href={cta.href} className="btn">
            {cta.label}
            <ArrowBox />
          </a>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={panelId}
            aria-label={open ? labels.closeMenu : labels.openMenu}
            onClick={() => setOpen((o) => !o)}
            className="-me-2.5 flex size-11 flex-col items-center justify-center gap-1 text-obsidian lg:hidden"
          >
            <i
              className="block h-px w-6 bg-current transition-transform duration-300 ease-brand"
              style={{ transform: open ? "translateY(2.5px) rotate(45deg)" : "none" }}
            />
            <i
              className="block h-px w-6 bg-current transition-transform duration-300 ease-brand"
              style={{ transform: open ? "translateY(-2.5px) rotate(-45deg)" : "none" }}
            />
          </button>
        </div>
      </div>

      {/* Mobile panel: grid-rows 0fr → 1fr */}
      <div
        id={panelId}
        className="grid transition-[grid-template-rows] duration-300 ease-brand lg:hidden"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
        inert={!open}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="shell max-h-[calc(100svh-var(--header-h))] overflow-y-auto overscroll-contain pb-6 pt-2">
            <ul className="m-0 list-none p-0">
              {links.map((l) => (
                <li key={l.href}>
                  <a
                    href={l.href}
                    onClick={() => setOpen(false)}
                    className="flex min-h-12 items-center border-b border-[var(--line)] text-[13px] uppercase tracking-[0.12em] text-carbon"
                  >
                    {l.label}
                  </a>
                </li>
              ))}
            </ul>
            <div className="mt-6 sm:hidden">
              <p className="m-0 mb-3 font-mono text-[10px] uppercase tracking-[0.16em] text-concrete">{labels.language}</p>
              <ul className="m-0 grid list-none grid-cols-4 gap-1 p-0">
                {locales.map((code) => (
                  <li key={code}>
                    <Link
                      href="/"
                      locale={code}
                      lang={code}
                      hrefLang={code}
                      aria-current={code === locale ? "true" : undefined}
                      onClick={() => setOpen(false)}
                      className={`flex min-h-11 items-center justify-center border font-mono text-[11px] uppercase tracking-[0.04em] ${
                        code === locale ? "border-obsidian text-obsidian" : "border-[var(--line-60)] text-carbon"
                      }`}
                    >
                      <span aria-hidden="true">{localeNames[code].short}</span>
                      <span className="sr-only">{localeNames[code].name}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}

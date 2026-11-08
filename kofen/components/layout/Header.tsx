import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { splitBadge } from "@/lib/text";
import { NavBar } from "./NavBar";

/** Sticky wrapper: announcement bar + main nav. */
export async function Header({ locale, base = "" }: { locale: Locale; base?: string }) {
  const t = await getTranslations({ locale });
  const { badge, text } = splitBadge(t("announcement.text"));

  return (
    <header className="sticky top-0 z-[60]">
      <a
        href={`${base}#pricing`}
        className="gutter-x flex h-9 items-center justify-center gap-3.5 overflow-hidden whitespace-nowrap bg-carbon font-mono text-[11px] uppercase tracking-[0.04em] text-signal transition-opacity duration-150 hover:opacity-70"
      >
        {badge && (
          <span className="inline-flex flex-none items-center gap-2">
            <span aria-hidden="true" className="blink-sq size-1.5 bg-rust" />
            {badge}
          </span>
        )}
        <span className="min-w-0 overflow-hidden text-ellipsis">{text}</span>
        <span className="hidden flex-none text-stone md:inline">{t("announcement.link")}</span>
      </a>
      <NavBar
        locale={locale}
        links={[
          { href: `${base}#deployment`, label: t("nav.deployment") },
          { href: `${base}#industries`, label: t("nav.industries") },
          { href: `${base}#pricing`, label: t("nav.engagement") },
          { href: `${base}#company`, label: t("nav.company") },
        ]}
        cta={{ href: `${base}#contact`, label: t("nav.cta") }}
        homeHref={`${base}#top`}
        labels={{
          language: t("ui.language"),
          openMenu: t("ui.openMenu"),
          closeMenu: t("ui.closeMenu"),
          home: t("ui.home"),
          mainNav: t("ui.mainNav"),
        }}
      />
    </header>
  );
}

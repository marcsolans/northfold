import { Button, Logo } from "@messer/ui";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { MarketingNav } from "./marketing-nav";

export async function SiteHeader() {
  const t = await getTranslations("marketing.nav");
  const links = [
    { href: "/#producto", label: t("product") },
    { href: "/templates", label: t("templates") },
    { href: "/pricing", label: t("pricing") },
    { href: "/security", label: t("security") },
    { href: "/docs", label: t("docs") },
    { href: "/blog", label: t("blog") },
  ];
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-bg/95 backdrop-blur supports-[backdrop-filter]:bg-bg/80">
      <a
        href="#contenido"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-1.5 focus:text-sm"
      >
        {t("skip")}
      </a>
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4 sm:px-6">
        <Link href="/" aria-label={t("home")} className="shrink-0">
          <Logo />
        </Link>
        <div className="flex flex-1 items-center justify-end gap-2 md:justify-between">
          <MarketingNav
            links={links}
            labels={{
              primary: t("primary"),
              openMenu: t("openMenu"),
              closeMenu: t("closeMenu"),
              login: t("login"),
              cta: t("cta"),
            }}
          />
          <div className="hidden items-center gap-2 md:flex">
            <Button asChild variant="ghost">
              <Link href="/login">{t("login")}</Link>
            </Button>
            <Button asChild variant="primary">
              <Link href="/signup">{t("cta")}</Link>
            </Button>
          </div>
        </div>
      </div>
    </header>
  );
}

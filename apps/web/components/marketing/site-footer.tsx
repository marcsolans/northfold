import { Logo } from "@messer/ui";
import { Globe, MapPin } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { Locale } from "@/i18n/config";

export async function SiteFooter({ locale }: { locale: Locale }) {
  const t = await getTranslations("marketing.footer");
  const columns = [
    {
      title: t("product"),
      links: [
        { href: "/#producto", label: t("overview") },
        { href: "/templates", label: t("templates") },
        { href: "/pricing", label: t("pricing") },
        { href: "/security", label: t("security") },
        { href: "/status", label: t("status") },
      ],
    },
    {
      title: t("resources"),
      links: [
        { href: "/docs", label: t("docs") },
        { href: "/docs/quickstart", label: t("quickstart") },
        { href: "/blog", label: t("blog") },
        { href: "/contact", label: t("contact") },
      ],
    },
    {
      title: t("legal"),
      links: [
        { href: "/legal/terms", label: t("terms") },
        { href: "/legal/privacy", label: t("privacy") },
        { href: "/legal/cookies", label: t("cookies") },
        { href: "/legal/dpa", label: t("dpa") },
        { href: "/legal/subprocessors", label: t("subprocessors") },
        { href: "/legal/aup", label: t("aup") },
      ],
    },
  ];
  return (
    <footer className="border-t border-border bg-subtle">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-12 sm:px-6 md:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div className="flex flex-col gap-3">
          <Logo />
          <p className="max-w-xs text-sm text-fg-muted">{t("tagline")}</p>
          <p className="flex max-w-xs items-start gap-2 text-xs text-fg-subtle">
            <MapPin className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {t("eu")}
          </p>
        </div>
        {columns.map((column) => (
          <nav key={column.title} aria-label={column.title}>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-subtle">{column.title}</h2>
            <ul className="mt-3 flex flex-col gap-2">
              {column.links.map((link) => (
                <li key={link.href}>
                  <Link href={link.href} className="text-sm text-fg-muted hover:text-fg">
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <div className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-5 text-xs text-fg-subtle sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>{t("rights", { year: new Date().getFullYear() })}</p>
          <div className="flex items-center gap-2" role="group" aria-label={t("language")}>
            <Globe className="size-3.5" aria-hidden />
            {/* Full page loads (not client navigations) so every message bundle switches language. */}
            <a
              href="?lang=es"
              hrefLang="es"
              lang="es"
              aria-current={locale === "es" ? "true" : undefined}
              className={locale === "es" ? "font-medium text-fg" : "hover:text-fg"}
            >
              {t("spanish")}
            </a>
            <span aria-hidden>·</span>
            <a
              href="?lang=en"
              hrefLang="en"
              lang="en"
              aria-current={locale === "en" ? "true" : undefined}
              className={locale === "en" ? "font-medium text-fg" : "hover:text-fg"}
            >
              {t("english")}
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}

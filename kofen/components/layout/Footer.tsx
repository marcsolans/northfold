import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { Link } from "@/i18n/navigation";
import { getCopy } from "@/lib/copy";
import { links, site } from "@/lib/site";
import { LanguageSelect } from "@/components/ui/LanguageSelect";

/**
 * Footer (signal): K monogram, 3 link columns, tagline; bottom bar with ©, legal
 * links and an upward-opening language selector. `base` prefixes in-page anchors
 * so they work from the legal pages too.
 */
export async function Footer({ locale, base = "" }: { locale: Locale; base?: string }) {
  const t = await getTranslations({ locale });
  const copy = await getCopy(locale);
  const f = copy.footer;
  const columns = [
    {
      head: f.headings.services,
      links: [
        { text: f.services.diagnostic, href: `${base}#pricing` },
        { text: f.services.deployment, href: `${base}#pricing` },
        { text: f.services.embeddedTeam, href: `${base}#deployment` },
      ],
    },
    {
      head: f.headings.industries,
      links: Object.values(copy.industries.items).map((it) => ({ text: it.name, href: `${base}#industries` })),
    },
    {
      head: f.headings.company,
      links: [
        { text: f.company.whyKofen, href: `${base}#company` },
        { text: f.company.careers, href: links.careers(f.company.careers) },
        { text: f.company.contact, href: `${base}#contact` },
      ],
    },
  ];
  const legal = [
    { text: f.legal.notice, href: "/legal/notice" },
    { text: f.legal.privacy, href: "/legal/privacy" },
    { text: f.legal.cookies, href: "/legal/cookies" },
  ] as const;

  return (
    <footer className="border-t border-hairline bg-signal">
      <div className="shell grid gap-x-10 gap-y-12 pb-14 pt-[72px] [grid-template-columns:repeat(auto-fit,minmax(min(180px,100%),1fr))]">
        <div className="flex items-center">
          <span aria-hidden="true" className="text-[76px] leading-none tracking-[-0.06em]">
            K
          </span>
          <span className="sr-only">Kofen</span>
        </div>
        {columns.map((col) => (
          <nav key={col.head} aria-label={col.head} className="hover-dim flex flex-col gap-3">
            <h2 className="m-0 font-mono text-[10px] font-normal uppercase tracking-[0.16em] text-concrete-deep">{col.head}</h2>
            <ul className="m-0 -my-2.5 flex list-none flex-col p-0">
              {col.links.map((l) => (
                <li key={l.text}>
                  <a href={l.href} className="inline-flex min-h-11 items-center text-[13px] text-carbon">
                    <span className="ul">{l.text}</span>
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        ))}
        <div className="flex flex-col gap-3.5">
          <span aria-hidden="true" className="size-2 bg-rust" />
          <p className="m-0 max-w-[12em] text-lg leading-[1.25] tracking-[-0.02em]">{f.tagline}</p>
          <p className="m-0 text-[13px] text-concrete-deep">
            <bdi>{site.cities}</bdi>
          </p>
        </div>
      </div>
      <div className="border-t border-hairline">
        <div className="shell flex flex-wrap items-center justify-between gap-x-8 gap-y-4 py-[18px]">
          <p className="m-0 font-mono text-[10px] uppercase tracking-[0.08em] text-concrete-deep">
            <bdi>
              © {site.year} Kofen · {site.cities}
            </bdi>
          </p>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <nav aria-label={t("ui.legalNav")} className="hover-dim flex flex-wrap gap-[18px]">
              {legal.map((l) => (
                <Link key={l.href} href={l.href} className="inline-flex min-h-11 items-center text-xs text-concrete-deep">
                  <span className="ul">{l.text}</span>
                </Link>
              ))}
            </nav>
            <LanguageSelect locale={locale} label={t("ui.language")} placement="up" variant="name" />
          </div>
        </div>
      </div>
    </footer>
  );
}

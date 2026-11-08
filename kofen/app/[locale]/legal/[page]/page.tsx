import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { setRequestLocale } from "next-intl/server";
import { routing, type Locale } from "@/i18n/routing";
import { getCopy } from "@/lib/copy";
import { LEGAL_PAGES, LEGAL_READY, type LegalPage } from "@/lib/legal";
import { alternatesFor } from "@/lib/seo";
import { site } from "@/lib/site";
import { legalContent, legalLanguageFor, type Block } from "@/content/legal";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";
import { Eyebrow } from "@/components/ui/primitives";

type Props = { params: Promise<{ locale: string; page: string }> };

export function generateStaticParams() {
  return LEGAL_PAGES.map((page) => ({ page }));
}

const isLegalPage = (p: string): p is LegalPage => (LEGAL_PAGES as readonly string[]).includes(p);

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, page } = await params;
  if (!hasLocale(routing.locales, locale) || !isLegalPage(page)) return {};
  const { footer } = await getCopy(locale);
  return {
    title: footer.legal[page],
    alternates: alternatesFor(locale, `/legal/${page}`),
    // Drafts with [TO COMPLETE] placeholders stay out of search results.
    robots: LEGAL_READY ? undefined : { index: false, follow: true },
  };
}

/** Renders [TO COMPLETE: …] placeholders as highlighted marks and fills {email}/{domain}. */
function Rich({ text }: { text: string }) {
  const filled = text.replaceAll("{email}", site.email).replaceAll("{domain}", site.url.replace(/^https?:\/\//, ""));
  const parts = filled.split(/(\[TO COMPLETE[^\]]*\])/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("[TO COMPLETE") ? (
          <mark key={i} className="bg-rust/25 px-1 font-mono text-[0.85em] text-obsidian">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  );
}

function BlockView({ block }: { block: Block }) {
  if (Array.isArray(block))
    return (
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {block.map((item) => (
          <li key={item} className="flex gap-3">
            <span aria-hidden="true" className="mt-[0.6em] size-[5px] flex-none bg-rust" />
            <span>
              <Rich text={item} />
            </span>
          </li>
        ))}
      </ul>
    );
  return (
    <p className="m-0">
      <Rich text={block} />
    </p>
  );
}

export default async function LegalPageView({ params }: Props) {
  const { locale: raw, page } = await params;
  if (!hasLocale(routing.locales, raw) || !isLegalPage(page)) notFound();
  const locale = raw as Locale;
  setRequestLocale(locale);
  const { footer } = await getCopy(locale);
  const lang = legalLanguageFor(locale);
  const doc = legalContent[lang][page];
  const base = `/${locale}`;

  return (
    <>
      <Header locale={locale} base={base} />
      <main id="main" tabIndex={-1} className="outline-none">
        <article className="shell py-24 md:py-32" lang={lang === locale ? undefined : lang}>
          <div className="max-w-[46rem]">
            <Eyebrow>{footer.headings.legal}</Eyebrow>
            <h1 className="mb-4 mt-6 text-[length:var(--fs-h2)] font-normal leading-[1.04] tracking-[-0.025em]">{footer.legal[page]}</h1>
            <p className="m-0 mb-14 font-mono text-[11px] uppercase tracking-[0.04em] text-concrete">
              <Rich text={doc.updated} />
            </p>
            <div className="flex flex-col gap-12">
              {doc.sections.map((s) => (
                <section key={s.heading} className="flex flex-col gap-4 border-t border-stone pt-6">
                  <h2 className="m-0 text-[21px] font-normal leading-[1.15] tracking-[-0.01em]">{s.heading}</h2>
                  <div className="flex flex-col gap-4 text-[15.5px] leading-[1.65] text-carbon">
                    {s.blocks.map((b, i) => (
                      <BlockView key={i} block={b} />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </article>
      </main>
      <Footer locale={locale} base={base} />
    </>
  );
}

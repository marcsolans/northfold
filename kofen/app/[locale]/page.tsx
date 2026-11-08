import type { Metadata } from "next";
import { hasLocale } from "next-intl";
import { setRequestLocale } from "next-intl/server";
import { routing } from "@/i18n/routing";
import { getCopy } from "@/lib/copy";
import { alternatesFor, localeUrl, ogLocale } from "@/lib/seo";
import { jsonLdString, organizationJsonLd } from "@/lib/jsonld";
import { site } from "@/lib/site";
import type { Locale } from "@/i18n/routing";
import { Header } from "@/components/layout/Header";
import { Hero } from "@/components/sections/hero/Hero";
import { LiveConsole } from "@/components/sections/console/LiveConsole";
import { SystemsStrip } from "@/components/sections/SystemsStrip";
import { Manifesto } from "@/components/sections/Manifesto";
import { Platform } from "@/components/sections/platform/Platform";
import { Phases } from "@/components/sections/phases/Phases";
import { Depth } from "@/components/sections/depth/Depth";
import { Industries } from "@/components/sections/industries/Industries";
import { Pricing } from "@/components/sections/Pricing";
import { Faq } from "@/components/sections/faq/Faq";
import { Company } from "@/components/sections/Company";
import { ClosingCta } from "@/components/sections/ClosingCta";
import { Footer } from "@/components/layout/Footer";

export async function generateMetadata({ params }: PageProps<"/[locale]">): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const { hero } = await getCopy(locale);
  const title = `${site.name} · ${hero.headline}`;
  return {
    title: { absolute: title },
    description: hero.sub,
    alternates: alternatesFor(locale),
    openGraph: {
      type: "website",
      siteName: site.name,
      url: localeUrl(locale),
      title,
      description: hero.sub,
      locale: ogLocale[locale],
      alternateLocale: routing.locales.filter((l) => l !== locale).map((l) => ogLocale[l]),
    },
    twitter: { card: "summary_large_image", title, description: hero.sub },
  };
}

export default async function Home({ params }: PageProps<"/[locale]">) {
  const { locale: raw } = await params;
  const locale = raw as Locale;
  setRequestLocale(locale);
  const { hero } = await getCopy(locale);
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdString(organizationJsonLd(hero.sub)) }} />
      <Header locale={locale} />
      <main id="main" tabIndex={-1} className="outline-none">
        <Hero locale={locale} />
        <LiveConsole locale={locale} />
        <SystemsStrip locale={locale} />
        <Manifesto locale={locale} />
        <Platform locale={locale} />
        <Phases locale={locale} />
        <Depth locale={locale} />
        <Industries locale={locale} />
        <Pricing locale={locale} />
        <Faq locale={locale} />
        <Company locale={locale} />
        <ClosingCta locale={locale} />
      </main>
      <Footer locale={locale} />
    </>
  );
}

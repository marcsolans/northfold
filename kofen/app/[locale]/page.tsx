import { setRequestLocale } from "next-intl/server";
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

export default async function Home({ params }: PageProps<"/[locale]">) {
  const { locale: raw } = await params;
  const locale = raw as Locale;
  setRequestLocale(locale);
  return (
    <>
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

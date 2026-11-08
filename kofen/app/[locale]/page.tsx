import { setRequestLocale } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { Header } from "@/components/layout/Header";
import { Hero } from "@/components/sections/hero/Hero";
import { LiveConsole } from "@/components/sections/console/LiveConsole";
import { SystemsStrip } from "@/components/sections/SystemsStrip";

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
        <div className="h-[100vh]" />
      </main>
    </>
  );
}

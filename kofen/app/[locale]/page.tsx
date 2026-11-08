import { setRequestLocale } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { Header } from "@/components/layout/Header";

export default async function Home({ params }: PageProps<"/[locale]">) {
  const { locale: raw } = await params;
  const locale = raw as Locale;
  setRequestLocale(locale);
  return (
    <>
      <Header locale={locale} />
      <main id="main" tabIndex={-1} className="outline-none">
        <div id="top" className="h-[200vh]" />
      </main>
    </>
  );
}

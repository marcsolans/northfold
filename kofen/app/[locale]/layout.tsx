import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { routing, isRtl } from "@/i18n/routing";
import { fontClasses, scriptFonts } from "@/lib/fonts";
import { site } from "@/lib/site";
import { RevealController } from "@/components/system/RevealController";
import "../globals.css";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export const viewport: Viewport = {
  themeColor: "#ffffff",
  colorScheme: "light",
};

export async function generateMetadata({ params }: LayoutProps<"/[locale]">): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const t = await getTranslations({ locale, namespace: "hero" });
  return {
    metadataBase: new URL(site.url),
    title: { default: `${site.name} · ${t("headline")}`, template: `%s · ${site.name}` },
    description: t("sub"),
    applicationName: site.name,
    formatDetection: { email: false, telephone: false, address: false },
  };
}

export default async function LocaleLayout({ children, params }: LayoutProps<"/[locale]">) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "ui" });
  const script = scriptFonts[locale];

  return (
    <html
      lang={locale}
      dir={isRtl(locale) ? "rtl" : "ltr"}
      className={fontClasses}
      style={script ? ({ "--font-script": script.family } as React.CSSProperties) : undefined}
    >
      <body>
        {script && <link rel="stylesheet" href={script.href} precedence="default" />}
        <a href="#main" className="skip-link">
          {t("skipToContent")}
        </a>
        {/* Client components receive their strings as props; no message catalogue is shipped. */}
        <NextIntlClientProvider locale={locale} messages={null}>
          {children}
        </NextIntlClientProvider>
        <RevealController />
      </body>
    </html>
  );
}

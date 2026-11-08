import { hasLocale } from "next-intl";
import { routing } from "@/i18n/routing";
import { renderOgImage, ogSize } from "@/lib/og";
import en from "@/messages/en.json";

export const size = ogSize;
export const contentType = "image/png";
export const alt = "Kofen";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export default async function Image({ params }: { params: Promise<{ locale: string }> }) {
  const { locale: raw } = await params;
  const locale = hasLocale(routing.locales, raw) ? raw : routing.defaultLocale;
  // next/og cannot shape Arabic script, so /ar shares the English card.
  const messages = locale === "ar" ? en : (await import(`@/messages/${locale}.json`)).default;
  return renderOgImage({ headline: messages.hero.headline, script: locale === "zh" ? "zh" : undefined });
}

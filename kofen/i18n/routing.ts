import { defineRouting } from "next-intl/routing";

export const locales = ["en", "es", "de", "fr", "it", "pt", "zh", "ar"] as const;
export type Locale = (typeof locales)[number];

export const routing = defineRouting({
  locales,
  defaultLocale: "en",
  // Every URL carries its locale (/en, /es…); `/` is redirected by Accept-Language.
  localePrefix: "always",
  // hreflang alternates are emitted in <head> via generateMetadata instead of a Link header.
  alternateLinks: false,
});

export const rtlLocales: readonly Locale[] = ["ar"];
export const isRtl = (locale: string) => (rtlLocales as readonly string[]).includes(locale);

/** Native names and short codes, as in the prototype's LANGS table. */
export const localeNames: Record<Locale, { short: string; name: string }> = {
  en: { short: "EN", name: "English" },
  es: { short: "ES", name: "Español" },
  de: { short: "DE", name: "Deutsch" },
  fr: { short: "FR", name: "Français" },
  it: { short: "IT", name: "Italiano" },
  pt: { short: "PT", name: "Português" },
  zh: { short: "ZH", name: "中文" },
  ar: { short: "AR", name: "العربية" },
};

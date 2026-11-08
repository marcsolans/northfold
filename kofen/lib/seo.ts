import type { Metadata } from "next";
import { routing, type Locale } from "@/i18n/routing";
import { site } from "./site";

/** Absolute URL for a locale + path, e.g. ("es", "/legal/privacy") → https://kofen.ai/es/legal/privacy */
export const localeUrl = (locale: Locale, path = "") => `${site.url}/${locale}${path}`;

/** Canonical + hreflang alternates (all locales and x-default) for a path. */
export function alternatesFor(locale: Locale, path = ""): Metadata["alternates"] {
  return {
    canonical: localeUrl(locale, path),
    languages: {
      ...Object.fromEntries(routing.locales.map((l) => [l, localeUrl(l, path)])),
      "x-default": localeUrl(routing.defaultLocale, path),
    },
  };
}

/** OpenGraph locale tags (language_TERRITORY). */
export const ogLocale: Record<Locale, string> = {
  en: "en_US",
  es: "es_ES",
  de: "de_DE",
  fr: "fr_FR",
  it: "it_IT",
  pt: "pt_PT",
  zh: "zh_CN",
  ar: "ar_AR",
};

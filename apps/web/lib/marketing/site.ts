import type { Metadata } from "next";
import { getLocale } from "next-intl/server";

import { type Locale, isLocale } from "@/i18n/config";

export function siteUrl(): string {
  return (process.env.MESSER_WEB_URL ?? "http://localhost:3000").replace(/\/$/, "");
}

export function absoluteUrl(path: string): string {
  return `${siteUrl()}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function currentLocale(): Promise<Locale> {
  const locale = await getLocale();
  return isLocale(locale) ? locale : "es";
}

/** Canonical URL plus language alternates (English is served on the same path with `?lang=en`). */
export function alternates(path: string): NonNullable<Metadata["alternates"]> {
  return {
    canonical: path,
    languages: { "es-ES": path, "en-GB": `${path}?lang=en`, "x-default": path },
  };
}

export function pageMetadata({
  title,
  description,
  path,
  locale,
  type = "website",
}: {
  title: string;
  description: string;
  path: string;
  locale: Locale;
  type?: "website" | "article";
}): Metadata {
  return {
    title,
    description,
    alternates: alternates(path),
    openGraph: {
      type,
      title,
      description,
      url: path,
      siteName: "Messer",
      locale: locale === "en" ? "en_GB" : "es_ES",
    },
    twitter: { card: "summary_large_image", title, description },
  };
}

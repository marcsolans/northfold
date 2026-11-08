import type { MetadataRoute } from "next";
import { routing } from "@/i18n/routing";
import { LEGAL_PAGES, LEGAL_READY } from "@/lib/legal";
import { localeUrl } from "@/lib/seo";

export default function sitemap(): MetadataRoute.Sitemap {
  const paths = ["", ...(LEGAL_READY ? LEGAL_PAGES.map((p) => `/legal/${p}`) : [])];
  return paths.flatMap((path) =>
    routing.locales.map((locale) => ({
      url: localeUrl(locale, path),
      changeFrequency: "monthly" as const,
      priority: path ? 0.3 : 1,
      alternates: {
        languages: {
          ...Object.fromEntries(routing.locales.map((l) => [l, localeUrl(l, path)])),
          "x-default": localeUrl(routing.defaultLocale, path),
        },
      },
    })),
  );
}

import { Geist, Geist_Mono, Noto_Sans_Arabic, Noto_Sans_SC } from "next/font/google";

export const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist",
  display: "swap",
});

export const geistMono = Geist_Mono({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-geist-mono",
  display: "swap",
});

/*
 * Script fonts for zh and ar. Both expose the same `--font-script` variable, and
 * the layout only applies the class for the active locale, so no other locale
 * downloads them (the @font-face rules exist, but browsers fetch a face only when
 * a glyph actually uses it). No preload: these are large, unicode-range-split files.
 */
export const notoSansSC = Noto_Sans_SC({
  subsets: ["latin"],
  weight: ["300", "400"],
  variable: "--font-script",
  display: "swap",
  preload: false,
});

export const notoSansArabic = Noto_Sans_Arabic({
  subsets: ["arabic"],
  weight: ["300", "400", "500"],
  variable: "--font-script",
  display: "swap",
  preload: false,
});

export function fontClasses(locale: string) {
  const base = `${geist.variable} ${geistMono.variable}`;
  if (locale === "zh") return `${base} ${notoSansSC.variable}`;
  if (locale === "ar") return `${base} ${notoSansArabic.variable}`;
  return base;
}

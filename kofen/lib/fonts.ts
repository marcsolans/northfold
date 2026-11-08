import { Geist, Geist_Mono } from "next/font/google";

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

/**
 * Script fonts for zh and ar, self-hosted by scripts/copy-script-fonts.mjs and
 * linked only on those locales (see app/[locale]/layout.tsx). They slot into the
 * font stacks through `--font-script`, after Geist, so Latin keeps Geist.
 */
export const scriptFonts: Partial<Record<string, { href: string; family: string }>> = {
  zh: { href: "/fonts/noto-sans-sc.css", family: "'Noto Sans SC Variable'" },
  ar: { href: "/fonts/noto-sans-arabic.css", family: "'Noto Sans Arabic Variable'" },
};

export const fontClasses = `${geist.variable} ${geistMono.variable}`;

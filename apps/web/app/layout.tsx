import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import type * as React from "react";

import { ConsentBanner } from "@/components/consent/consent-banner";
import { AppProviders } from "@/components/providers/app-providers";

import "./globals.css";

const siteUrl = process.env.MESSER_WEB_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: { default: "Messer — IA en producción para empresas", template: "%s · Messer" },
  description:
    "Describe tu problema. Messer construye la solución —agentes, flujos, conocimiento e interfaces— y la pone en producción con gobierno, trazabilidad y control de costes. Infraestructura en la UE.",
  applicationName: "Messer",
  openGraph: { type: "website", siteName: "Messer", locale: "es_ES" },
  icons: { icon: "/favicon.svg" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0f0f0f" },
  ],
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang={locale} className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <body className="min-h-screen bg-bg text-fg">
        <NextIntlClientProvider locale={locale} messages={messages}>
          <AppProviders nonce={nonce}>
            {children}
            <ConsentBanner />
          </AppProviders>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}

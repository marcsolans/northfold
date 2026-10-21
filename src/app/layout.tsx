import type { Metadata, Viewport } from "next";
import { Poppins } from "next/font/google";
import { Toaster } from "react-hot-toast";

import { env } from "@/env";
import { STORE } from "@/lib/store-config";

import "./globals.css";

const poppins = Poppins({
  weight: ["300", "400", "500", "600"],
  style: ["normal"],
  subsets: ["latin"],
  display: "swap",
  variable: "--font-poppins",
});

export const metadata: Metadata = {
  metadataBase: new URL(env.NEXT_PUBLIC_APP_URL),
  title: { default: `${STORE.name} — ${STORE.tagline}`, template: `%s · ${STORE.name}` },
  description: STORE.description,
  applicationName: STORE.name,
  openGraph: {
    type: "website",
    siteName: STORE.name,
    title: STORE.name,
    description: STORE.description,
    locale: "en_US",
  },
  twitter: { card: "summary_large_image" },
};

export const viewport: Viewport = {
  themeColor: "#faf9f6",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={poppins.variable}>
      <body className="flex min-h-dvh flex-col">
        {children}
        <Toaster
          position="bottom-right"
          toastOptions={{
            duration: 4000,
            className: "!rounded-md !bg-primary !text-primary-foreground !text-sm !shadow-lg",
            success: {
              iconTheme: {
                primary: "var(--color-success-soft)",
                secondary: "var(--color-success)",
              },
            },
            error: {
              iconTheme: {
                primary: "var(--color-destructive-soft)",
                secondary: "var(--color-destructive)",
              },
            },
          }}
        />
      </body>
    </html>
  );
}

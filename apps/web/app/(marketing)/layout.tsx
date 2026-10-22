import type * as React from "react";

import { SiteFooter } from "@/components/marketing/site-footer";
import { SiteHeader } from "@/components/marketing/site-header";
import { currentLocale } from "@/lib/marketing/site";

export default async function MarketingLayout({ children }: { children: React.ReactNode }) {
  const locale = await currentLocale();
  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <SiteHeader />
      <main id="contenido" className="flex-1">
        {children}
      </main>
      <SiteFooter locale={locale} />
    </div>
  );
}

import { ChevronDown } from "lucide-react";
import { getTranslations } from "next-intl/server";
import type * as React from "react";

import { DocsNav } from "@/components/docs/docs-nav";
import { Container } from "@/components/marketing/section";
import { docsNav } from "@/lib/content/docs";
import { currentLocale } from "@/lib/marketing/site";

export default async function DocsLayout({ children }: { children: React.ReactNode }) {
  const t = await getTranslations("docsSite");
  const sections = docsNav(await currentLocale());
  return (
    <Container className="py-8 sm:py-12">
      <div className="grid gap-8 lg:grid-cols-[220px_minmax(0,1fr)] lg:gap-12">
        <aside className="lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:self-start lg:overflow-y-auto">
          <details className="group rounded-md border border-border lg:hidden [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-sm font-medium text-fg">
              {t("menu")}
              <ChevronDown className="size-4 text-fg-subtle transition-transform group-open:rotate-180" aria-hidden />
            </summary>
            <div className="border-t border-border p-3">
              <DocsNav sections={sections} label={t("nav")} />
            </div>
          </details>
          <div className="hidden lg:block">
            <DocsNav sections={sections} label={t("nav")} />
          </div>
        </aside>
        <div className="min-w-0">{children}</div>
      </div>
    </Container>
  );
}

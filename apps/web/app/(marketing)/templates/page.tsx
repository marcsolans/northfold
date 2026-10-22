import { Badge, Button } from "@messer/ui";
import {
  BarChart3,
  Check,
  FileSearch,
  FileSpreadsheet,
  Headphones,
  type LucideIcon,
  Package,
  Phone,
  Scale,
  Target,
  Users,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Container, Section, SectionHeader } from "@/components/marketing/section";
import type { TemplateItem } from "@/lib/marketing/content-types";
import { currentLocale, pageMetadata } from "@/lib/marketing/site";

const ICONS: Record<string, LucideIcon> = {
  "invoice-support": Headphones,
  "lead-qualification": Target,
  "document-extraction": FileSpreadsheet,
  "hr-assistant": Users,
  "contract-analysis": Scale,
  "orders-stock": Package,
  "phone-receptionist": Phone,
  "weekly-sales-report": BarChart3,
};

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("marketing.templatesPage");
  return pageMetadata({
    title: t("metaTitle"),
    description: t("metaDescription"),
    path: "/templates",
    locale: await currentLocale(),
  });
}

export default async function TemplatesPage() {
  const t = await getTranslations("marketing");
  const templates = t.raw("templates.items") as TemplateItem[];
  const steps = t.raw("templatesPage.steps") as string[];

  return (
    <>
      <Container className="py-14 sm:py-20">
        <SectionHeader
          as="h1"
          eyebrow={t("templatesPage.eyebrow")}
          title={t("templatesPage.title")}
          subtitle={t("templatesPage.subtitle")}
        />
        <ol className="mt-8 grid gap-3 sm:grid-cols-3" aria-label={t("templatesPage.stepsTitle")}>
          {steps.map((step, i) => (
            <li key={step} className="flex items-start gap-3 rounded-md border border-border bg-subtle px-4 py-3 text-sm text-fg">
              <span className="tabular flex size-6 shrink-0 items-center justify-center rounded-full bg-fg text-xs font-semibold text-bg">
                {i + 1}
              </span>
              {step}
            </li>
          ))}
        </ol>
      </Container>

      <Section tone="subtle" className="pt-12 sm:pt-14">
        <ul className="grid gap-3 md:grid-cols-2">
          {templates.map((tpl) => {
            const Icon = ICONS[tpl.id] ?? FileSearch;
            return (
              <li key={tpl.id} id={tpl.id} className="flex scroll-mt-20 flex-col rounded-md border border-border bg-surface p-5">
                <div className="flex items-start justify-between gap-3">
                  <span className="flex size-9 items-center justify-center rounded-md border border-border bg-subtle">
                    <Icon className="size-4 text-fg" aria-hidden />
                  </span>
                  <Badge tone="outline">{tpl.sector}</Badge>
                </div>
                <h2 className="mt-4 text-md font-semibold text-fg">{tpl.title}</h2>
                <p className="mt-2 text-sm leading-relaxed text-fg-muted">{tpl.body}</p>
                <p className="mt-4 text-xs font-medium text-fg-subtle">{t("templates.includes")}</p>
                <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
                  {tpl.includes.map((item) => (
                    <li key={item} className="flex items-start gap-2 text-sm text-fg">
                      <Check className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
                      {item}
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      </Section>

      <section className="border-t border-border" aria-labelledby="templates-cta">
        <Container className="flex flex-col items-start gap-5 py-14 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 id="templates-cta" className="text-lg font-semibold tracking-tight text-fg">
              {t("templatesPage.ctaTitle")}
            </h2>
            <p className="mt-1 text-sm text-fg-muted">{t("templatesPage.ctaBody")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="primary" size="lg">
              <Link href="/signup">{t("templatesPage.cta")}</Link>
            </Button>
            <Button asChild variant="secondary" size="lg">
              <Link href="/contact?topic=sales">{t("templatesPage.ctaSecondary")}</Link>
            </Button>
          </div>
        </Container>
      </section>
    </>
  );
}

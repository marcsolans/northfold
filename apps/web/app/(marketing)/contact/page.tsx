import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Container, SectionHeader } from "@/components/marketing/section";
import { isContactTopic } from "@/lib/marketing/contact";
import { eur } from "@/lib/marketing/pricing";
import { getPlans } from "@/lib/marketing/public-api";
import { currentLocale, pageMetadata } from "@/lib/marketing/site";

import { ContactForm } from "./contact-form";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("contact");
  return pageMetadata({
    title: t("metaTitle"),
    description: t("metaDescription"),
    path: "/contact",
    locale: await currentLocale(),
  });
}

function AsideBlock({ title, body, href, link }: { title: string; body: string; href: string; link: string }) {
  return (
    <div className="border-t border-border pt-4">
      <h2 className="text-base font-semibold text-fg">{title}</h2>
      <p className="mt-1 text-sm leading-relaxed text-fg-muted">{body}</p>
      <Link href={href} className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-fg hover:underline">
        {link}
        <ArrowRight className="size-3.5" aria-hidden />
      </Link>
    </div>
  );
}

export default async function ContactPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const t = await getTranslations("contact");
  const locale = await currentLocale();
  const params = await searchParams;
  const topic = isContactTopic(params.topic) ? params.topic : "sales";
  const plans = await getPlans();
  const enterprise = plans.ok ? plans.data.find((p) => p.price_is_starting) : undefined;

  return (
    <Container className="py-14 sm:py-20">
      <div className="grid gap-10 lg:grid-cols-[1.6fr_1fr]">
        <div>
          <SectionHeader as="h1" eyebrow={t("eyebrow")} title={t("title")} subtitle={t("subtitle")} />
          <div className="mt-8">
            <ContactForm initialTopic={topic} />
          </div>
        </div>
        <aside className="flex flex-col gap-6 lg:pt-24">
          <AsideBlock
            title={t("aside.enterpriseTitle")}
            body={`${t("aside.enterpriseBody")}${enterprise ? ` ${t("aside.enterpriseFrom", { price: eur(enterprise.price_month_eur, locale) })}` : ""}`}
            href="/pricing"
            link={t("aside.pricingLink")}
          />
          <AsideBlock title={t("aside.supportTitle")} body={t("aside.supportBody")} href="/docs" link={t("aside.docsLink")} />
          <AsideBlock title={t("aside.securityTitle")} body={t("aside.securityBody")} href="/security" link={t("aside.trustLink")} />
        </aside>
      </div>
    </Container>
  );
}

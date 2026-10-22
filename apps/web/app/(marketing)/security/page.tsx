import { Button } from "@messer/ui";
import {
  Activity,
  ArrowRight,
  Bot,
  Check,
  FileLock2,
  FileText,
  Globe2,
  KeyRound,
  ListChecks,
  type LucideIcon,
  ScrollText,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Container, Section, SectionHeader } from "@/components/marketing/section";
import type { SecuritySection } from "@/lib/marketing/content-types";
import { currentLocale, pageMetadata } from "@/lib/marketing/site";

const ICONS: Record<string, LucideIcon> = {
  residency: Globe2,
  isolation: ShieldCheck,
  encryption: FileLock2,
  access: KeyRound,
  audit: ScrollText,
  ai: Bot,
  operations: Wrench,
  gdpr: FileText,
};

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("marketing.securityPage");
  return pageMetadata({
    title: t("metaTitle"),
    description: t("metaDescription"),
    path: "/security",
    locale: await currentLocale(),
  });
}

export default async function SecurityPage() {
  const t = await getTranslations("marketing.securityPage");
  const sections = t.raw("sections") as SecuritySection[];
  const quickLinks = [
    { href: "/legal/dpa", label: t("quickLinks.dpa"), icon: FileText },
    { href: "/legal/subprocessors", label: t("quickLinks.subprocessors"), icon: ListChecks },
    { href: "/legal/privacy", label: t("quickLinks.privacy"), icon: ShieldCheck },
    { href: "/status", label: t("quickLinks.status"), icon: Activity },
  ];

  return (
    <>
      <Container className="py-14 sm:py-20">
        <SectionHeader as="h1" eyebrow={t("eyebrow")} title={t("title")} subtitle={t("subtitle")} />
        <ul className="mt-8 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {quickLinks.map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface px-4 py-3 text-sm font-medium text-fg hover:bg-subtle"
              >
                <span className="flex items-center gap-2">
                  <link.icon className="size-4 text-fg-subtle" aria-hidden />
                  {link.label}
                </span>
                <ArrowRight className="size-4 text-fg-subtle" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </Container>

      <Section tone="subtle" className="pt-12 sm:pt-14">
        <div className="grid gap-3 md:grid-cols-2">
          {sections.map((section) => {
            const Icon = ICONS[section.key] ?? ShieldCheck;
            return (
              <article key={section.key} id={section.key} className="scroll-mt-20 rounded-md border border-border bg-surface p-5">
                <div className="flex items-center gap-2">
                  <Icon className="size-4 text-accent" aria-hidden />
                  <h2 className="text-md font-semibold text-fg">{section.title}</h2>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-fg-muted">{section.body}</p>
                <ul className="mt-3 flex flex-col gap-2">
                  {section.points.map((point) => (
                    <li key={point} className="flex items-start gap-2 text-sm leading-relaxed text-fg">
                      <Check className="mt-1 size-3.5 shrink-0 text-success" aria-hidden />
                      {point}
                    </li>
                  ))}
                </ul>
              </article>
            );
          })}
        </div>
      </Section>

      <Section labelledBy="subprocessors-title">
        <div className="grid gap-8 md:grid-cols-2">
          <div>
            <h2 id="subprocessors-title" className="text-lg font-semibold tracking-tight text-fg">
              {t("subprocessorsTitle")}
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-fg-muted">{t("subprocessorsBody")}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button asChild variant="secondary">
                <Link href="/legal/subprocessors">{t("subprocessorsCta")}</Link>
              </Button>
              <Button asChild variant="ghost">
                <Link href="/legal/dpa">{t("dpaCta")}</Link>
              </Button>
            </div>
          </div>
          <div className="rounded-md border border-border bg-subtle p-5">
            <h2 className="text-md font-semibold text-fg">{t("reportTitle")}</h2>
            <p className="mt-2 text-sm leading-relaxed text-fg-muted">{t("reportBody")}</p>
            <Button asChild variant="dark" className="mt-4">
              <Link href="/contact?topic=security">{t("reportCta")}</Link>
            </Button>
          </div>
        </div>
      </Section>
    </>
  );
}

import { Badge, Button } from "@messer/ui";
import {
  ArrowRight,
  Bot,
  Check,
  ClipboardCheck,
  Database,
  FileLock2,
  GitBranch,
  Globe2,
  KeyRound,
  LayoutPanelTop,
  type LucideIcon,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { ComposerAnimation } from "@/components/marketing/composer-animation";
import { Container, Faq, JsonLd, Section, SectionHeader } from "@/components/marketing/section";
import type { FaqItem, Pillar, SecurityItem, TemplateItem, UseCase } from "@/lib/marketing/content-types";
import { eur } from "@/lib/marketing/pricing";
import { getPlans } from "@/lib/marketing/public-api";
import { organizationLd, softwareApplicationLd } from "@/lib/marketing/structured-data";
import { currentLocale, pageMetadata } from "@/lib/marketing/site";

const PILLAR_ICONS: Record<string, LucideIcon> = {
  composer: Sparkles,
  agents: Bot,
  workflows: GitBranch,
  knowledge: Database,
  interfaces: LayoutPanelTop,
  governance: ScrollText,
};

const SECURITY_ICONS: Record<string, LucideIcon> = {
  residency: Globe2,
  isolation: ShieldCheck,
  secrets: FileLock2,
  approvals: ClipboardCheck,
  access: KeyRound,
  audit: Users,
};

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("marketing.meta");
  const locale = await currentLocale();
  return {
    ...pageMetadata({ title: t("homeTitle"), description: t("homeDescription"), path: "/", locale }),
    title: { absolute: t("homeTitle") },
  };
}

export default async function LandingPage() {
  const locale = await currentLocale();
  const t = await getTranslations("marketing");
  const plans = await getPlans();

  const pillars = t.raw("pillars.items") as Pillar[];
  const security = t.raw("security.items") as SecurityItem[];
  const templates = t.raw("templates.items") as TemplateItem[];
  const useCases = t.raw("useCases.items") as UseCase[];
  const faq = t.raw("faq.items") as FaqItem[];
  const codePoints = t.raw("code.points") as string[];

  return (
    <>
      <JsonLd
        data={[
          organizationLd(t("meta.homeDescription")),
          softwareApplicationLd(t("meta.homeDescription"), plans.ok ? plans.data : null),
        ]}
      />

      {/* ---------------------------------------------------------------- hero */}
      <section className="overflow-hidden" aria-labelledby="hero-title">
        <Container className="grid items-center gap-10 py-14 sm:py-20 lg:grid-cols-[1fr_1.1fr] lg:gap-12">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-accent">{t("hero.eyebrow")}</p>
            <h1
              id="hero-title"
              className="mt-3 text-[32px] font-semibold leading-[1.1] tracking-tight text-fg sm:text-2xl lg:text-[44px]"
            >
              {t("hero.title")}
            </h1>
            <p className="mt-5 max-w-xl text-md leading-relaxed text-fg-muted">{t("hero.subtitle")}</p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Button asChild variant="primary" size="lg">
                <Link href="/signup">
                  {t("hero.ctaPrimary")}
                  <ArrowRight />
                </Link>
              </Button>
              <Button asChild variant="secondary" size="lg">
                <Link href="/pricing">{t("hero.ctaSecondary")}</Link>
              </Button>
            </div>
            <p className="mt-4 text-sm text-fg-subtle">{t("hero.note")}</p>
          </div>
          <ComposerAnimation />
        </Container>
      </section>

      {/* ---------------------------------------------------------------- pillars */}
      <Section id="producto" labelledBy="pillars-title">
        <SectionHeader
          id="pillars-title"
          eyebrow={t("pillars.eyebrow")}
          title={t("pillars.title")}
          subtitle={t("pillars.subtitle")}
        />
        <div className="mt-10 grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
          {pillars.map((pillar) => {
            const Icon = PILLAR_ICONS[pillar.key] ?? Sparkles;
            return (
              <article key={pillar.key} className="flex flex-col bg-surface p-5">
                <span className="flex size-8 items-center justify-center rounded-md border border-border bg-subtle">
                  <Icon className="size-4 text-fg" aria-hidden />
                </span>
                <h3 className="mt-4 text-md font-semibold text-fg">{pillar.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-fg-muted">{pillar.body}</p>
                <ul className="mt-4 flex flex-col gap-1.5">
                  {pillar.points.map((point) => (
                    <li key={point} className="flex items-start gap-2 text-sm text-fg">
                      <Check className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
                      {point}
                    </li>
                  ))}
                </ul>
              </article>
            );
          })}
        </div>
      </Section>

      {/* ---------------------------------------------------------------- exportable code */}
      <Section tone="subtle" labelledBy="code-title">
        <div className="grid items-center gap-10 lg:grid-cols-2">
          <div>
            <SectionHeader id="code-title" eyebrow={t("code.eyebrow")} title={t("code.title")} subtitle={t("code.body")} />
            <ul className="mt-6 flex flex-col gap-2">
              {codePoints.map((point) => (
                <li key={point} className="flex items-start gap-2 text-sm text-fg">
                  <Check className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
                  {point}
                </li>
              ))}
            </ul>
          </div>
          <figure className="min-w-0 overflow-hidden rounded-md border border-border bg-surface">
            <figcaption className="flex h-9 items-center border-b border-border px-3 font-mono text-xs text-fg-muted">
              {t("code.fileName")}
            </figcaption>
            <pre className="overflow-x-auto p-4 font-mono text-[12.5px] leading-relaxed text-fg">
              <code>{t.raw("code.snippet") as string}</code>
            </pre>
          </figure>
        </div>
      </Section>

      {/* ---------------------------------------------------------------- security */}
      <Section labelledBy="security-title">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <SectionHeader
            id="security-title"
            eyebrow={t("security.eyebrow")}
            title={t("security.title")}
            subtitle={t("security.subtitle")}
          />
          <Button asChild variant="secondary">
            <Link href="/security">
              {t("security.cta")}
              <ArrowRight />
            </Link>
          </Button>
        </div>
        <div className="mt-10 grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
          {security.map((item) => {
            const Icon = SECURITY_ICONS[item.key] ?? ShieldCheck;
            return (
              <div key={item.key} className="flex gap-3">
                <Icon className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
                <div>
                  <h3 className="text-base font-semibold text-fg">{item.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-fg-muted">{item.body}</p>
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      {/* ---------------------------------------------------------------- templates */}
      <Section tone="subtle" labelledBy="templates-title">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <SectionHeader
            id="templates-title"
            eyebrow={t("templates.eyebrow")}
            title={t("templates.title")}
            subtitle={t("templates.subtitle")}
          />
          <Button asChild variant="secondary">
            <Link href="/templates">
              {t("templates.cta")}
              <ArrowRight />
            </Link>
          </Button>
        </div>
        <ul className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {templates.map((tpl) => (
            <li key={tpl.id} className="flex flex-col rounded-md border border-border bg-surface p-4">
              <Badge tone="outline" className="self-start">
                {tpl.sector}
              </Badge>
              <h3 className="mt-3 text-base font-semibold text-fg">{tpl.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-fg-muted">{tpl.body}</p>
            </li>
          ))}
        </ul>
      </Section>

      {/* ---------------------------------------------------------------- use cases */}
      <Section labelledBy="usecases-title">
        <SectionHeader id="usecases-title" eyebrow={t("useCases.eyebrow")} title={t("useCases.title")} />
        <div className="mt-10 grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
          {useCases.map((uc) => (
            <div key={uc.team} className="border-t border-border pt-4">
              <h3 className="text-base font-semibold text-fg">{uc.team}</h3>
              <ul className="mt-3 flex flex-col gap-1.5">
                {uc.examples.map((example) => (
                  <li key={example} className="flex items-start gap-2 text-sm text-fg-muted">
                    <span className="mt-2 size-1 shrink-0 rounded-full bg-fg-subtle" aria-hidden />
                    {example}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Section>

      {/* ---------------------------------------------------------------- pricing teaser (live prices) */}
      <Section tone="subtle" labelledBy="pricing-teaser-title">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <SectionHeader
            id="pricing-teaser-title"
            eyebrow={t("pricingTeaser.eyebrow")}
            title={t("pricingTeaser.title")}
            subtitle={t("pricingTeaser.subtitle")}
          />
          <Button asChild variant="secondary">
            <Link href="/pricing">
              {t("pricingTeaser.cta")}
              <ArrowRight />
            </Link>
          </Button>
        </div>
        {plans.ok ? (
          <ul className="mt-10 grid gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
            {plans.data.map((plan) => (
              <li key={plan.id} className="bg-surface p-5">
                <p className="text-sm font-semibold text-fg">{plan.name}</p>
                <p className="mt-2 text-fg">
                  {plan.price_is_starting ? (
                    <span className="mr-1 text-sm text-fg-muted">{t("pricingTeaser.from")}</span>
                  ) : null}
                  <span className="tabular text-xl font-semibold tracking-tight">{eur(plan.price_month_eur, locale)}</span>
                  <span className="text-sm text-fg-muted">{t("pricingTeaser.perMonth")}</span>
                </p>
                <p className="mt-2 text-sm text-fg-muted">{plan.description}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-8 text-sm text-fg-muted">{t("pricingTeaser.unavailable")}</p>
        )}
      </Section>

      {/* ---------------------------------------------------------------- FAQ */}
      <Section labelledBy="faq-title">
        <div className="grid gap-10 lg:grid-cols-[1fr_1.6fr]">
          <SectionHeader id="faq-title" eyebrow={t("faq.eyebrow")} title={t("faq.title")} />
          <Faq items={faq} />
        </div>
      </Section>

      {/* ---------------------------------------------------------------- final CTA */}
      <section className="border-t border-border bg-fg text-bg" aria-labelledby="final-cta-title">
        <Container className="flex flex-col items-start gap-6 py-16 md:flex-row md:items-center md:justify-between">
          <div className="max-w-2xl">
            <h2 id="final-cta-title" className="text-xl font-semibold tracking-tight">
              {t("finalCta.title")}
            </h2>
            <p className="mt-3 text-md text-bg/75">{t("finalCta.subtitle")}</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button asChild variant="primary" size="lg">
              <Link href="/signup">{t("finalCta.primary")}</Link>
            </Button>
            <Button asChild size="lg" className="border-bg/25 bg-transparent text-bg hover:bg-bg/10">
              <Link href="/contact?topic=sales">{t("finalCta.secondary")}</Link>
            </Button>
          </div>
        </Container>
      </section>
    </>
  );
}

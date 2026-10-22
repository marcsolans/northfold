import { Badge, Button, cn } from "@messer/ui";
import { ArrowRight, Check, Minus, RefreshCw } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Container, Faq, JsonLd, Section, SectionHeader } from "@/components/marketing/section";
import { annualDiscountPct, annualSaving, eur, maxAnnualDiscountPct, monthlyEquivalent } from "@/lib/marketing/pricing";
import {
  type CreditPack,
  type CreditPricing,
  type PublicPlan,
  UNLIMITED,
  getCreditPacks,
  getCreditPricing,
  getPlans,
} from "@/lib/marketing/public-api";
import { softwareApplicationLd } from "@/lib/marketing/structured-data";
import { currentLocale, pageMetadata } from "@/lib/marketing/site";

const TRIAL_PLAN = "pro";
const LIMIT_ROWS = ["seats", "projects", "runs_month", "credits_month", "storage_gb"] as const;
const ANNUAL_ID = "billing-annual";
// Visible price depends on the radio state, with CSS only (no client JavaScript on this page).
const PERIOD_SWITCH =
  "[&:has(#billing-annual:checked)_[data-period=month]]:hidden [&:not(:has(#billing-annual:checked))_[data-period=year]]:hidden";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("marketing.pricing");
  return pageMetadata({
    title: t("metaTitle"),
    description: t("metaDescription"),
    path: "/pricing",
    locale: await currentLocale(),
  });
}

type T = Awaited<ReturnType<typeof getTranslations<"marketing">>>;

function limitLine(t: T, key: (typeof LIMIT_ROWS)[number], value: number): string {
  switch (key) {
    case "seats":
      return value === UNLIMITED ? t("pricing.seatsUnlimited") : t("pricing.seats", { count: value });
    case "projects":
      return value === UNLIMITED ? t("pricing.projectsUnlimited") : t("pricing.projects", { count: value });
    case "runs_month":
      return value === UNLIMITED ? t("pricing.runsUnlimited") : t("pricing.runs", { count: value });
    case "credits_month":
      return t("pricing.credits", { count: value });
    case "storage_gb":
      return t("pricing.storage", { count: value });
  }
}

function featureLabel(t: T, key: string): string {
  return t.has(`features.${key}`) ? t(`features.${key}`) : key.replace(/_/g, " ");
}

function PlanCard({ plan, previous, t, locale }: { plan: PublicPlan; previous?: PublicPlan; t: T; locale: string }) {
  const trial = plan.id === TRIAL_PLAN;
  const added = plan.limits.features.filter((f) => !previous?.limits.features.includes(f));
  const discount = annualDiscountPct(plan);
  const cta = plan.self_serve
    ? { href: `/signup?plan=${encodeURIComponent(plan.id)}`, label: trial ? t("pricing.ctaTrial") : t("pricing.ctaStart", { plan: plan.name }) }
    : { href: "/contact?topic=enterprise", label: t("pricing.ctaContact") };
  return (
    <article
      className={cn(
        "flex flex-col rounded-md border bg-surface p-5",
        trial ? "border-fg shadow-[0_0_0_1px_var(--fg)]" : "border-border",
      )}
      aria-labelledby={`plan-${plan.id}`}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 id={`plan-${plan.id}`} className="text-md font-semibold text-fg">
          {plan.name}
        </h2>
        {trial ? <Badge tone="accent">{t("pricing.trialBadge")}</Badge> : null}
      </div>
      <p className="mt-1 min-h-10 text-sm text-fg-muted">{plan.description}</p>

      <div className="mt-4 min-h-[76px]">
        <div data-period="month">
          <p className="text-fg">
            {plan.price_is_starting ? <span className="mr-1 text-sm text-fg-muted">{t("pricing.from")}</span> : null}
            <span className="tabular text-xl font-semibold tracking-tight">{eur(plan.price_month_eur, locale)}</span>
            <span className="text-sm text-fg-muted">{t("pricing.perMonth")}</span>
          </p>
          <p className="mt-1 text-xs text-fg-subtle">{t("pricing.billedMonthly")}</p>
        </div>
        <div data-period="year">
          <p className="text-fg">
            {plan.price_is_starting ? <span className="mr-1 text-sm text-fg-muted">{t("pricing.from")}</span> : null}
            <span className="tabular text-xl font-semibold tracking-tight">{eur(plan.price_year_eur, locale)}</span>
            <span className="text-sm text-fg-muted">{t("pricing.perYear")}</span>
          </p>
          <p className="mt-1 text-xs text-fg-subtle">
            {t("pricing.equivalent", { price: eur(monthlyEquivalent(plan).toFixed(2), locale) })}
            {discount > 0 ? ` · ${t("pricing.save", { amount: eur(annualSaving(plan), locale) })}` : ""}
          </p>
        </div>
      </div>

      <Button asChild variant={trial ? "primary" : "secondary"} className="mt-4 w-full">
        <Link href={cta.href}>{cta.label}</Link>
      </Button>

      <ul className="mt-5 flex flex-col gap-1.5 border-t border-border pt-4">
        {LIMIT_ROWS.map((key) => (
          <li key={key} className="flex items-start gap-2 text-sm text-fg">
            <Check className="mt-0.5 size-3.5 shrink-0 text-fg-subtle" aria-hidden />
            {limitLine(t, key, Number(plan.limits[key]))}
          </li>
        ))}
      </ul>
      {added.length ? (
        <div className="mt-4">
          <p className="text-xs font-medium text-fg-subtle">
            {previous ? t("pricing.includesPrevious", { plan: previous.name }) : t("pricing.includes")}
          </p>
          <ul className="mt-2 flex flex-col gap-1.5">
            {added.map((f) => (
              <li key={f} className="flex items-start gap-2 text-sm text-fg">
                <Check className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
                {featureLabel(t, f)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </article>
  );
}

function ComparisonTable({ plans, t, locale }: { plans: PublicPlan[]; t: T; locale: string }) {
  const features = Array.from(new Set(plans.flatMap((p) => p.limits.features)));
  const cell = "border-b border-border px-3 py-2.5 text-sm";
  const value = (plan: PublicPlan, key: (typeof LIMIT_ROWS)[number]) => {
    const n = Number(plan.limits[key]);
    return n === UNLIMITED ? t("pricing.unlimited") : new Intl.NumberFormat(locale === "en" ? "en-GB" : "es-ES").format(n);
  };
  return (
    <div className="mt-8 overflow-x-auto rounded-md border border-border bg-surface">
      <table className="w-full min-w-[640px] border-collapse text-left">
        <caption className="sr-only">{t("pricing.compareTitle")}</caption>
        <thead>
          <tr className="bg-subtle">
            <th scope="col" className={cn(cell, "sticky left-0 z-10 bg-subtle text-xs font-semibold uppercase tracking-wide text-fg-subtle")}>
              {t("pricing.compareFeature")}
            </th>
            {plans.map((plan) => (
              <th key={plan.id} scope="col" className={cn(cell, "text-sm font-semibold text-fg")}>
                {plan.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row" className={cn(cell, "sticky left-0 bg-surface font-normal text-fg-muted")}>
              {t("pricing.rows.price")}
            </th>
            {plans.map((plan) => (
              <td key={plan.id} className={cn(cell, "tabular text-fg")}>
                {plan.price_is_starting ? `${t("pricing.from")} ` : ""}
                {eur(plan.price_month_eur, locale)}
                {t("pricing.perMonth")}
              </td>
            ))}
          </tr>
          <tr>
            <th colSpan={plans.length + 1} scope="colgroup" className="border-b border-border bg-subtle px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
              {t("pricing.limitsGroup")}
            </th>
          </tr>
          {LIMIT_ROWS.map((key) => (
            <tr key={key}>
              <th scope="row" className={cn(cell, "sticky left-0 bg-surface font-normal text-fg-muted")}>
                {t(`pricing.rows.${key}`)}
              </th>
              {plans.map((plan) => (
                <td key={plan.id} className={cn(cell, "tabular text-fg")}>
                  {value(plan, key)}
                </td>
              ))}
            </tr>
          ))}
          <tr>
            <th colSpan={plans.length + 1} scope="colgroup" className="border-b border-border bg-subtle px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
              {t("pricing.featuresGroup")}
            </th>
          </tr>
          {features.map((feature) => (
            <tr key={feature}>
              <th scope="row" className={cn(cell, "sticky left-0 bg-surface font-normal text-fg-muted")}>
                {featureLabel(t, feature)}
              </th>
              {plans.map((plan) => {
                const has = plan.limits.features.includes(feature);
                return (
                  <td key={plan.id} className={cell}>
                    {has ? (
                      <Check className="size-4 text-success" aria-label={t("pricing.included")} />
                    ) : (
                      <Minus className="size-4 text-fg-subtle" aria-label={t("pricing.notIncluded")} />
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CreditsSection({
  packs,
  pricing,
  t,
  locale,
}: {
  packs: CreditPack[] | null;
  pricing: CreditPricing | null;
  t: T;
  locale: string;
}) {
  const nf = new Intl.NumberFormat(locale === "en" ? "en-GB" : "es-ES", { maximumFractionDigits: 2 });
  return (
    <Section id="creditos" tone="subtle" labelledBy="credits-title">
      <SectionHeader id="credits-title" title={t("pricing.creditsTitle")} subtitle={t("pricing.creditsSubtitle")} />
      {pricing ? (
        <div className="mt-6 flex flex-wrap gap-2">
          <Badge tone="outline" className="px-2 py-1 text-sm">
            {t("pricing.creditValue", { usd: pricing.credit_usd })}
          </Badge>
          <Badge tone="outline" className="px-2 py-1 text-sm">
            {t("pricing.creditMargin", { pct: nf.format(Number(pricing.margin_pct)) })}
          </Badge>
        </div>
      ) : null}
      <div className="mt-8 grid gap-8 lg:grid-cols-2">
        <div>
          <h3 className="text-base font-semibold text-fg">{t("pricing.packsTitle")}</h3>
          {packs ? (
            <ul className="mt-3 divide-y divide-border rounded-md border border-border bg-surface">
              {packs.map((pack) => (
                <li key={pack.id} className="flex items-center justify-between gap-4 px-4 py-3">
                  <div>
                    <p className="text-sm font-medium text-fg">{t("pricing.packCredits", { count: pack.credits })}</p>
                    <p className="text-xs text-fg-subtle">
                      {t("pricing.packPer1000", {
                        price: eur(((Number(pack.price_eur) / pack.credits) * 1000).toFixed(2), locale, 2),
                      })}
                    </p>
                  </div>
                  <p className="tabular text-md font-semibold text-fg">{eur(pack.price_eur, locale)}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-fg-muted">{t("pricing.packsUnavailable")}</p>
          )}
        </div>
        <div>
          <h3 className="text-base font-semibold text-fg">{t("pricing.ratesTitle")}</h3>
          {pricing && pricing.models.length ? (
            <>
              <div className="mt-3 overflow-x-auto rounded-md border border-border bg-surface">
                <table className="w-full border-collapse text-left text-sm">
                  <thead className="bg-subtle text-xs uppercase tracking-wide text-fg-subtle">
                    <tr>
                      <th scope="col" className="border-b border-border px-3 py-2 font-semibold">{t("pricing.rateTier")}</th>
                      <th scope="col" className="border-b border-border px-3 py-2 font-semibold">{t("pricing.rateModel")}</th>
                      <th scope="col" className="border-b border-border px-3 py-2 text-right font-semibold">{t("pricing.rateInput")}</th>
                      <th scope="col" className="border-b border-border px-3 py-2 text-right font-semibold">{t("pricing.rateOutput")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pricing.models.map((m) => (
                      <tr key={m.tier} className="[&:last-child>td]:border-b-0">
                        <td className="border-b border-border px-3 py-2 font-medium text-fg">{t(`pricing.tiers.${m.tier}`)}</td>
                        <td className="border-b border-border px-3 py-2 text-fg-muted">{m.display_name}</td>
                        <td className="tabular border-b border-border px-3 py-2 text-right text-fg">{nf.format(Number(m.input_credits_per_mtok))}</td>
                        <td className="tabular border-b border-border px-3 py-2 text-right text-fg">{nf.format(Number(m.output_credits_per_mtok))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-fg-subtle">{t("pricing.ratesNote")}</p>
            </>
          ) : (
            <p className="mt-3 text-sm text-fg-muted">{t("pricing.ratesUnavailable")}</p>
          )}
        </div>
      </div>
    </Section>
  );
}

export default async function PricingPage() {
  const locale = await currentLocale();
  const t = await getTranslations("marketing");
  const [plans, packs, creditPricing] = await Promise.all([getPlans(), getCreditPacks(), getCreditPricing()]);
  const pricing = creditPricing.ok ? creditPricing.data : null;
  const enterprise = plans.ok ? plans.data.find((p) => p.price_is_starting) : undefined;
  const nf = new Intl.NumberFormat(locale === "en" ? "en-GB" : "es-ES", { maximumFractionDigits: 2 });

  const faq = [
    {
      q: t("pricing.faq.creditQ"),
      a: pricing ? t("pricing.faq.creditA", { usd: pricing.credit_usd }) : t("pricing.faq.creditAGeneric"),
    },
    {
      q: t("pricing.faq.usageQ"),
      a: pricing ? t("pricing.faq.usageA", { pct: nf.format(Number(pricing.margin_pct)) }) : t("pricing.faq.usageAGeneric"),
    },
    { q: t("pricing.faq.outQ"), a: t("pricing.faq.outA") },
    { q: t("pricing.faq.trialQ"), a: t("pricing.faq.trialA") },
    { q: t("pricing.faq.changeQ"), a: t("pricing.faq.changeA") },
    { q: t("pricing.faq.vatQ"), a: t("pricing.faq.vatA") },
    {
      q: t("pricing.faq.enterpriseQ"),
      a: enterprise
        ? t("pricing.faq.enterpriseA", { price: eur(enterprise.price_month_eur, locale) })
        : t("pricing.faq.enterpriseAGeneric"),
    },
  ];

  return (
    <>
      {plans.ok ? <JsonLd data={softwareApplicationLd(t("meta.homeDescription"), plans.data)} /> : null}
      <Container className="py-14 sm:py-20">
        <SectionHeader as="h1" eyebrow={t("pricing.eyebrow")} title={t("pricing.title")} subtitle={t("pricing.subtitle")} />

        {plans.ok ? (
          <div className={cn("mt-10", PERIOD_SWITCH)}>
            <fieldset className="inline-flex rounded-md border border-border bg-subtle p-0.5">
              <legend className="sr-only">{t("pricing.billingLabel")}</legend>
              {[
                { id: "billing-monthly", label: t("pricing.monthly"), checked: true },
                {
                  id: ANNUAL_ID,
                  label: t("pricing.annual"),
                  checked: false,
                  extra: maxAnnualDiscountPct(plans.data) > 0 ? t("pricing.annualSave", { pct: maxAnnualDiscountPct(plans.data) }) : null,
                },
              ].map((option) => (
                <label
                  key={option.id}
                  htmlFor={option.id}
                  className="flex cursor-pointer items-center gap-2 rounded-[6px] px-3 py-1.5 text-sm text-fg-muted has-[:checked]:bg-surface has-[:checked]:font-medium has-[:checked]:text-fg has-[:checked]:shadow-[0_0_0_1px_var(--border)] has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring"
                >
                  <input
                    id={option.id}
                    type="radio"
                    name="billing-period"
                    defaultChecked={option.checked}
                    className="sr-only"
                  />
                  {option.label}
                  {"extra" in option && option.extra ? <Badge tone="success">{option.extra}</Badge> : null}
                </label>
              ))}
            </fieldset>

            <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {plans.data.map((plan, i) => (
                <PlanCard key={plan.id} plan={plan} previous={i > 0 ? plans.data[i - 1] : undefined} t={t} locale={locale} />
              ))}
            </div>
            <p className="mt-4 text-xs text-fg-subtle">{t("pricing.vat")}</p>

            <h2 className="mt-16 text-lg font-semibold tracking-tight text-fg">{t("pricing.compareTitle")}</h2>
            <ComparisonTable plans={plans.data} t={t} locale={locale} />
          </div>
        ) : (
          <div role="alert" className="mt-10 max-w-2xl rounded-md border border-warning/25 bg-warning-soft p-5">
            <p className="text-base font-semibold text-fg">{t("pricing.unavailableTitle")}</p>
            <p className="mt-1 text-sm text-fg-muted">{t("pricing.unavailableBody")}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button asChild variant="secondary" size="sm">
                <a href="/pricing">
                  <RefreshCw />
                  {t("pricing.reload")}
                </a>
              </Button>
              <Button asChild variant="ghost" size="sm">
                <Link href="/contact?topic=sales">{t("pricing.contact")}</Link>
              </Button>
            </div>
          </div>
        )}
      </Container>

      <CreditsSection packs={packs.ok ? packs.data : null} pricing={pricing} t={t} locale={locale} />

      <Section labelledBy="pricing-faq-title">
        <div className="grid gap-10 lg:grid-cols-[1fr_1.6fr]">
          <SectionHeader id="pricing-faq-title" title={t("pricing.faqTitle")} />
          <Faq items={faq} />
        </div>
      </Section>

      <section className="border-t border-border" aria-labelledby="enterprise-title">
        <Container className="flex flex-col items-start gap-5 py-14 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 id="enterprise-title" className="text-lg font-semibold tracking-tight text-fg">
              {t("pricing.enterpriseTitle")}
            </h2>
            <p className="mt-1 text-sm text-fg-muted">
              {t("pricing.enterpriseBody")}
              {enterprise ? ` ${t("pricing.from")} ${eur(enterprise.price_month_eur, locale)}${t("pricing.perMonth")}.` : ""}
            </p>
          </div>
          <Button asChild variant="dark" size="lg">
            <Link href="/contact?topic=enterprise">
              {t("pricing.enterpriseCta")}
              <ArrowRight />
            </Link>
          </Button>
        </Container>
      </section>
    </>
  );
}

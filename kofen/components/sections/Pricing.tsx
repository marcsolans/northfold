import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { getCopy } from "@/lib/copy";
import { Eyebrow, Square, TwoToneHeading } from "@/components/ui/primitives";

/** Section 10 (#pricing): two hairline-separated plan cells. Prices live in messages/<locale>.json. */
export async function Pricing({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale });
  const { pricing } = await getCopy(locale);
  const plans = Object.values(pricing.plans);
  return (
    <section id="pricing" aria-labelledby="pricing-title" className="gutter-x border-t border-hairline bg-signal py-[140px]">
      <div data-reveal="" className="mx-auto flex max-w-[var(--container)] flex-col gap-14">
        <div className="flex flex-wrap items-end justify-between gap-x-20 gap-y-6">
          <div className="flex min-w-0 flex-[1_1_520px] flex-col gap-6">
            <Eyebrow className="text-concrete-deep">{t("nav.engagement")}</Eyebrow>
            <TwoToneHeading id="pricing-title" text={pricing.title} locale={locale} className="max-w-[14em]" />
          </div>
          <p className="m-0 min-w-0 flex-[0_1_420px] text-[15.5px] leading-[1.65] text-concrete-deep">{pricing.intro}</p>
        </div>
        <div className="grid gap-px border border-[rgba(46,46,46,0.3)] bg-[rgba(46,46,46,0.3)] [grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr))]">
          {plans.map((plan, i) => {
            const dark = i === 1;
            return (
              <article
                key={plan.name}
                className={`flex min-h-[300px] flex-col justify-between gap-8 p-9 ${dark ? "bg-carbon text-white" : "bg-white text-obsidian"}`}
              >
                <h3
                  className={`m-0 inline-flex items-center gap-2.5 font-mono text-[11px] font-normal uppercase tracking-[0.04em] ${
                    dark ? "text-stone" : "text-concrete"
                  }`}
                >
                  <Square />
                  {plan.name}
                </h3>
                <div className="flex flex-col gap-4">
                  <p className="m-0 text-[clamp(44px,5vw,76px)] leading-none tracking-[-0.05em] tabular-nums">{plan.price}</p>
                  <p className={`m-0 max-w-[30em] text-[14.5px] leading-[1.65] ${dark ? "text-stone" : "text-concrete"}`}>{plan.note}</p>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { getCopy } from "@/lib/copy";
import { links } from "@/lib/site";
import { ArrowBox, Eyebrow, TwoToneHeading } from "@/components/ui/primitives";

/** Section 12 (#company): two-tone H2, paragraph and two large cards. */
export async function Company({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale });
  const { company } = await getCopy(locale);
  const card = "flex min-h-[280px] items-end justify-between gap-4 p-8";
  const label = "text-[clamp(28px,2.6vw,40px)] leading-[1.05] tracking-[-0.035em]";
  return (
    <section id="company" aria-labelledby="company-title" className="gutter-x border-t border-hairline py-[140px]">
      <div data-reveal="" className="mx-auto flex max-w-[var(--container)] flex-col gap-14">
        <div className="flex flex-wrap items-end justify-between gap-x-20 gap-y-6">
          <div className="flex min-w-0 flex-[1_1_560px] flex-col gap-6">
            <Eyebrow>{t("nav.company")}</Eyebrow>
            <TwoToneHeading id="company-title" text={company.title} locale={locale} className="max-w-[15em]" />
          </div>
          <p className="m-0 min-w-0 flex-[0_1_440px] text-[15.5px] leading-[1.65] text-concrete">{company.body}</p>
        </div>
        <div className="grid gap-6 [grid-template-columns:repeat(auto-fit,minmax(min(380px,100%),1fr))]">
          <a href={links.story} className={`${card} bg-signal text-obsidian`}>
            <span className={label}>{company.storyCard}</span>
            <ArrowBox size="lg" />
          </a>
          <a href={links.careers(company.positionsCard)} className={`${card} bg-carbon text-white hover:text-white`}>
            <span className={label}>{company.positionsCard}</span>
            <ArrowBox size="lg" />
          </a>
        </div>
      </div>
    </section>
  );
}

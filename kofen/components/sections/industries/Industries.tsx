import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { getCopy } from "@/lib/copy";
import { ButtonLink, Eyebrow, TwoToneHeading } from "@/components/ui/primitives";
import { IndustryRail } from "./IndustryRail";

/** Section 9 (#industries): header + horizontal rail of 7 square cards. */
export async function Industries({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale });
  const { industries } = await getCopy(locale);
  return (
    <section id="industries" aria-labelledby="industries-title" className="gutter-x py-[140px]">
      <div data-reveal="" className="mx-auto flex max-w-[var(--container)] flex-col gap-10">
        <div className="flex flex-wrap items-end justify-between gap-x-20 gap-y-6">
          <div className="flex min-w-0 flex-[1_1_520px] flex-col gap-6">
            <Eyebrow>{t("nav.industries")}</Eyebrow>
            <TwoToneHeading id="industries-title" text={industries.title} locale={locale} className="max-w-[13em]" />
          </div>
          <ButtonLink href="#contact" variant="ghost">
            {industries.cta}
          </ButtonLink>
        </div>
        <IndustryRail
          items={Object.values(industries.items)}
          href="#contact"
          labels={{ previous: t("ui.previous"), next: t("ui.next") }}
        />
      </div>
    </section>
  );
}

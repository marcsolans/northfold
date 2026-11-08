import type { Locale } from "@/i18n/routing";
import { getCopy } from "@/lib/copy";
import { ButtonLink, Eyebrow, TwoToneHeading } from "@/components/ui/primitives";
import { FaqList } from "./FaqList";

/** Section 11 (#faq): eyebrow, H2, CTA to the console composer, 6 accordion items. */
export async function Faq({ locale }: { locale: Locale }) {
  const { faq, composer } = await getCopy(locale);
  return (
    <section id="faq" aria-labelledby="faq-title" className="gutter-x py-[140px]">
      <div data-reveal="" className="mx-auto flex max-w-[var(--container)] flex-wrap items-start gap-x-20 gap-y-12">
        <div className="flex min-w-0 flex-[1_1_340px] flex-col items-start gap-7">
          <Eyebrow>FAQ</Eyebrow>
          <TwoToneHeading id="faq-title" text={faq.title} locale={locale} className="max-w-[10em]" />
          <ButtonLink href="#try">{composer.send}</ButtonLink>
        </div>
        <FaqList items={Object.values(faq.items)} />
      </div>
    </section>
  );
}

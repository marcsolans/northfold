import type { Locale } from "@/i18n/routing";
import { getCopy } from "@/lib/copy";
import { TwoToneHeading } from "@/components/ui/primitives";
import { PhasesClient } from "./PhasesClient";

/** Section 7 (#phases): stepper with autoplay and the "work led by Kofen" share. */
export async function Phases({ locale }: { locale: Locale }) {
  const { phases } = await getCopy(locale);
  return (
    <section id="phases" aria-labelledby="phases-title" className="gutter-x py-[140px]">
      <div data-reveal="" className="mx-auto flex max-w-[var(--container)] flex-col gap-11">
        <TwoToneHeading id="phases-title" text={phases.title} locale={locale} className="max-w-[15em]" />
        <PhasesClient
          phases={Object.values(phases.items)}
          tabLabel={phases.tab}
          ledByKofen={phases.ledByKofen}
          listLabel={phases.title}
        />
      </div>
    </section>
  );
}

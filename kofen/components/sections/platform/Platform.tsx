import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { getCopy } from "@/lib/copy";
import { pad2 } from "@/lib/text";
import { ButtonLink, Eyebrow, TwoToneHeading } from "@/components/ui/primitives";
import { LayersDiagram } from "./LayersDiagram";

/** Section 6 (#deployment): pillars + sticky, scroll-assembled "Kofen layers" diagram. */
export async function Platform({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale });
  const { platform } = await getCopy(locale);
  return (
    <section
      id="deployment"
      aria-labelledby="deployment-title"
      className="gutter-x border-t border-hairline bg-signal py-[150px] lg:min-h-[1240px]"
    >
      <div className="mx-auto flex max-w-[var(--container)] flex-wrap items-start gap-x-20 gap-y-16 lg:min-h-[940px]">
        <div data-reveal="" className="flex min-w-0 max-w-[560px] flex-[1_1_420px] flex-col gap-10">
          <Eyebrow className="text-concrete-deep">{t("nav.deployment")}</Eyebrow>
          <TwoToneHeading id="deployment-title" text={platform.title} locale={locale} />
          <ButtonLink href="#phases" className="self-start">
            {platform.pillars[0].cta}
          </ButtonLink>
          <div className="flex flex-col">
            {platform.pillars.map((p, i) => (
              <div key={p.title} className="flex gap-5 border-t border-stone py-[26px]">
                <span className="flex-none pt-[3px] font-mono text-[11px] text-concrete-deep">{pad2(i + 1)}</span>
                <div className="flex flex-col gap-2">
                  <h3 className="m-0 text-lg font-normal tracking-[-0.015em]">{p.title}</h3>
                  <p className="m-0 text-[14.5px] leading-[1.65] text-concrete-deep">{p.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
        {/* The column stretches the whole runway so the diagram can stay pinned (≥1024px). */}
        <div dir="ltr" className="min-w-0 flex-[1_1_520px] lg:self-stretch">
          <div className="flex justify-center lg:sticky lg:top-[140px]">
            <LayersDiagram
              sectionId="deployment"
              label="Kofen layers: your systems, governance, agents and forward-deployed engineers"
            />
          </div>
        </div>
      </div>
    </section>
  );
}

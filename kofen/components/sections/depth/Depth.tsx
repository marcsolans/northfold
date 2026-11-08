import type { Locale } from "@/i18n/routing";
import { getCopy } from "@/lib/copy";
import { Eyebrow, TwoToneHeading } from "@/components/ui/primitives";
import { StatCounters } from "./StatCounters";

/** Prototype NUMS: [final value, suffix] per stat, in copy order. */
const STAT_VALUES: Record<string, [number, string]> = {
  diagnosticDays: [7, ""],
  minimumReturn: [5, "×"],
  proposalDays: [2, ""],
  ownSystems: [100, "%"],
};

/** Section 8 (#platform): hairline-grid panel, 3 pillar cells + 4 counting stats. */
export async function Depth({ locale }: { locale: Locale }) {
  const { depth } = await getCopy(locale);
  const stats = Object.entries(depth.stats).map(([id, label]) => ({
    value: STAT_VALUES[id][0],
    suffix: STAT_VALUES[id][1],
    label,
  }));
  return (
    <section id="platform" aria-labelledby="platform-title" className="gutter-x bg-stone py-[120px]">
      <div data-reveal="" className="mx-auto flex max-w-[var(--container)] flex-col gap-12">
        <TwoToneHeading id="platform-title" text={depth.title} locale={locale} mutedClassName="text-umber" className="max-w-[14em]" />
        <div className="flex flex-col gap-px border border-[rgba(46,46,46,0.35)] bg-[rgba(46,46,46,0.35)]">
          <div className="grid grid-cols-1 gap-px md:grid-cols-3">
            {Object.values(depth.pillars).map((p) => (
              <div key={p.label} className="flex flex-col gap-3.5 bg-signal p-9">
                <Eyebrow className="text-concrete-deep">{p.label}</Eyebrow>
                <h3 className="m-0 mt-3 text-[21px] font-normal leading-[1.15] tracking-[-0.01em]">{p.title}</h3>
                <p className="m-0 text-[14.5px] leading-[1.65] text-concrete-deep">{p.body}</p>
              </div>
            ))}
          </div>
          <StatCounters stats={stats} />
        </div>
      </div>
    </section>
  );
}

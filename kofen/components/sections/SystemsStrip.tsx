import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { SYSTEMS } from "@/lib/systems";
import { Eyebrow } from "@/components/ui/primitives";

/** Section 4: mono eyebrow + infinite marquee of system names with edge fade. */
export async function SystemsStrip({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale, namespace: "systems" });
  const item =
    "flex h-[84px] flex-none items-center whitespace-nowrap border-e border-[rgba(184,174,164,0.35)] px-11 text-xl tracking-[-0.025em] text-concrete";
  return (
    <section className="flex flex-col items-center gap-7 pt-16" aria-labelledby="systems-title">
      <Eyebrow as="h2" className="px-6 text-center text-concrete">
        <span id="systems-title">{t("title")}</span>
      </Eyebrow>
      <div dir="ltr" className="marquee-wrap edge-fade w-full overflow-hidden border-y border-[var(--line)]">
        <div className="marquee">
          <ul className="m-0 flex list-none p-0">
            {SYSTEMS.map((name) => (
              <li key={name} className={item}>
                {name}
              </li>
            ))}
          </ul>
          <ul aria-hidden="true" className="m-0 flex list-none p-0">
            {SYSTEMS.map((name) => (
              <li key={name} className={item}>
                {name}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

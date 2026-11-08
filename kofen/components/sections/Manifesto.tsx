import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";

/** Section 5: two-tone statement. */
export async function Manifesto({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale, namespace: "manifesto" });
  return (
    <section id="kofen-man" className="gutter-x flex justify-center py-40">
      <p
        data-reveal=""
        className="m-0 max-w-[980px] text-center text-[clamp(32px,4.2vw,62px)] leading-[1.08] tracking-[-0.045em] text-balance"
      >
        <span className="text-obsidian">{t("lead")}</span> <span className="text-concrete">{t("emphasis")}</span>
      </p>
    </section>
  );
}

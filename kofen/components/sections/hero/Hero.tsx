import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { site } from "@/lib/site";
import { getCopy } from "@/lib/copy";
import { EmailForm } from "@/components/ui/EmailForm";
import { HeroLattice } from "./HeroLattice";
import { PhraseRotator } from "./PhraseRotator";
import { PointerSheen } from "./PointerSheen";

export async function Hero({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale });
  const copy = await getCopy(locale);
  const phrases = copy.hero.rotator;

  return (
    <section
      id="top"
      className="relative min-h-[680px] overflow-hidden text-obsidian"
      style={{ background: "var(--grad-hero)", "--gx": "40px" } as React.CSSProperties}
    >
      <HeroLattice />
      <PointerSheen targetId="top" resetTo={40} />
      <div className="shell relative z-[1] flex min-h-[680px] flex-col items-start justify-center pb-[72px] pt-24">
        <div className="max-w-[11.5em] text-[length:var(--fs-display)] font-normal leading-[1.04] tracking-[-0.055em]">
          <h1 className="sheen m-0 text-balance font-normal [font:inherit] [letter-spacing:inherit]">
            {t("hero.headline")} <span className="sr-only">{phrases[0]}</span>
          </h1>
          <PhraseRotator phrases={phrases} />
        </div>
        <EmailForm
          source="hero"
          locale={locale}
          placeholder={t("hero.emailPlaceholder")}
          cta={t("hero.cta")}
          mailSubject={t("nav.cta")}
          email={site.email}
          messages={copy.ui.form}
          className="mt-10 w-full max-w-[480px]"
        />
        <p className="m-0 mt-6 max-w-[28em] text-xl leading-[1.4] text-carbon">{t("hero.sub")}</p>
      </div>
    </section>
  );
}

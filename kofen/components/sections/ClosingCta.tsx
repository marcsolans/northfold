import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { getCopy } from "@/lib/copy";
import { mailto, site } from "@/lib/site";
import { EmailForm } from "@/components/ui/EmailForm";
import { PointerSheen } from "@/components/sections/hero/PointerSheen";

/** Static lattice collage (≥1024px): 7×5 grid of 80px cells, tonal tiles and quarter arcs (prototype). */
function LatticeCollage() {
  const cells = [];
  for (let c = 0; c < 7; c++) for (let r = 0; r < 5; r++) cells.push([c * 80, r * 80]);
  return (
    <svg viewBox="0 0 560 400" className="block h-auto w-full">
      <g fill="none" stroke="#b8aea4" strokeWidth="1">
        {cells.map(([x, y]) => (
          <rect key={`${x}-${y}`} x={x} y={y} width="80" height="80" />
        ))}
      </g>
      <rect x="80" y="80" width="80" height="80" fill="#d59566" />
      <rect x="320" y="240" width="80" height="80" fill="#2e2e2e" />
      <rect x="400" y="0" width="80" height="80" fill="#b8aea4" />
      <rect x="160" y="320" width="80" height="80" fill="#736f6a" />
      <g fill="none" stroke="#070707" strokeWidth="1">
        <path d="M0,80 A80,80 0 0 1 80,0" />
        <path d="M240,160 A80,80 0 0 0 320,80" />
        <path d="M480,160 A80,80 0 0 1 560,240" />
        <path d="M160,160 A80,80 0 0 0 240,240" />
        <path d="M400,400 A80,80 0 0 1 480,320" />
      </g>
    </svg>
  );
}

/** Section 13 (#contact): gradient band, display H2 with the hero sheen, inline email form, email link. */
export async function ClosingCta({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale });
  const copy = await getCopy(locale);
  return (
    <section
      id="contact"
      aria-labelledby="contact-title"
      className="gutter-x relative overflow-hidden pb-[clamp(80px,6.9vw,120px)] pt-[clamp(96px,8.2vw,140px)]"
      style={{ background: "var(--grad-cta)", "--gx": "200px" } as React.CSSProperties}
    >
      <PointerSheen targetId="contact" />
      <div className="mx-auto flex max-w-[var(--container)] flex-wrap items-center justify-between gap-12">
        <div data-reveal="" className="flex min-w-0 flex-[1_1_520px] flex-col gap-10">
          <h2
            id="contact-title"
            className="sheen m-0 max-w-[11em] text-[clamp(40px,5vw,88px)] font-normal leading-[1.04] tracking-[-0.055em] text-balance"
          >
            {copy.closing.title}
          </h2>
          <EmailForm
            source="contact"
            tone="contact"
            locale={locale}
            placeholder={copy.hero.emailPlaceholder}
            cta={copy.closing.cta}
            mailSubject={t("nav.cta")}
            email={site.email}
            messages={copy.ui.form}
            className="w-full max-w-[480px]"
          />
          <a
            href={mailto(copy.composer.emailSubject)}
            className="-mt-4 inline-flex min-h-11 items-center self-start font-mono text-[11px] uppercase tracking-[0.04em] text-umber"
          >
            <span className="ul">{site.email}</span>
          </a>
        </div>
        <div aria-hidden="true" className="hidden min-w-0 flex-[0_1_560px] lg:block">
          <LatticeCollage />
        </div>
      </div>
    </section>
  );
}

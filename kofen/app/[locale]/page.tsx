import { setRequestLocale, getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";

export default async function Home({ params }: PageProps<"/[locale]">) {
  const { locale } = await params;
  setRequestLocale(locale as Locale);
  const t = await getTranslations({ locale: locale as Locale, namespace: "hero" });
  return (
    <main id="main" className="shell py-24">
      <h1 className="sheen text-[length:var(--fs-display)] leading-[1.04] tracking-[-0.055em]">{t("headline")}</h1>
      <p className="mt-6 max-w-[28em] text-xl text-carbon">{t("sub")}</p>
    </main>
  );
}

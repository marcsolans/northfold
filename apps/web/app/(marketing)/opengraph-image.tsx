import { getTranslations } from "next-intl/server";

import { OG_SIZE, ogImage } from "@/lib/marketing/og";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Messer";

export default async function OpenGraphImage() {
  const t = await getTranslations("marketing");
  return ogImage({ eyebrow: t("hero.eyebrow"), title: t("hero.title"), footer: t("meta.ogTagline") });
}

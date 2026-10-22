import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { OnboardingFlow } from "./onboarding-flow";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("onboarding");
  return { title: t("metaTitle") };
}

export default async function OnboardingPage() {
  const t = await getTranslations("onboarding");
  return (
    <>
      <div className="mb-8 max-w-2xl">
        <p className="text-xs font-semibold uppercase tracking-wide text-accent">{t("eyebrow")}</p>
        <h1 className="mt-2 text-xl font-semibold tracking-tight text-fg">{t("title")}</h1>
        <p className="mt-2 text-md text-fg-muted">{t("subtitle")}</p>
      </div>
      <Suspense>
        <OnboardingFlow />
      </Suspense>
    </>
  );
}

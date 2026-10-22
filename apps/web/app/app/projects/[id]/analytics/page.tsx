"use client";

import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense } from "react";

import { AnalyticsDashboard } from "@/components/analytics/dashboard";
import { EvalComparisonCard } from "@/components/analytics/eval-comparison";

export default function ProjectAnalyticsPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("analytics");
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 py-6 md:px-6">
      <div>
        <h1 className="text-lg font-semibold text-fg">{t("projectTitle")}</h1>
        <p className="mt-1 text-sm text-fg-muted">{t("projectDescription")}</p>
      </div>
      <Suspense>
        <AnalyticsDashboard projectId={id}>
          <EvalComparisonCard projectId={id} />
        </AnalyticsDashboard>
      </Suspense>
    </div>
  );
}

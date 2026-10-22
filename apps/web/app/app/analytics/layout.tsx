"use client";

import { PageHeader } from "@messer/ui";
import { useTranslations } from "next-intl";
import type * as React from "react";
import { Suspense } from "react";

import { AnalyticsNav } from "@/components/analytics/analytics-nav";

export default function AnalyticsLayout({ children }: { children: React.ReactNode }) {
  const t = useTranslations("analytics");
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5 px-4 py-6 md:px-8">
      <div>
        <PageHeader title={t("title")} description={t("description")} className="pb-3" />
        <Suspense>
          <AnalyticsNav />
        </Suspense>
      </div>
      {children}
    </div>
  );
}

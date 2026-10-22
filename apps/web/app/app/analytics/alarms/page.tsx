"use client";

import { Suspense } from "react";

import { AlarmsManager } from "@/components/analytics/alarms";

export default function AlarmsPage() {
  return (
    <Suspense>
      <AlarmsManager />
    </Suspense>
  );
}

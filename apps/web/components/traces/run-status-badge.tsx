"use client";

import { Badge, StatusDot } from "@messer/ui";
import { useTranslations } from "next-intl";

import { runStatusTone } from "@/lib/studio/format";
import { RUN_STATUSES, type RunStatus } from "@/lib/studio/types";

export function useRunStatusLabel() {
  const t = useTranslations("traces.status");
  return (status: string) => (RUN_STATUSES.includes(status as RunStatus) ? t(status as RunStatus) : status);
}

export function RunStatusBadge({ status, className }: { status: string; className?: string }) {
  const label = useRunStatusLabel();
  const tone = runStatusTone(status);
  return (
    <Badge tone={tone} className={className}>
      <StatusDot tone={tone} pulse={status === "running"} />
      {label(status)}
    </Badge>
  );
}

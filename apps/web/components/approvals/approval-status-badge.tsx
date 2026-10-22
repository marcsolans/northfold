"use client";

import { Badge, StatusDot } from "@messer/ui";
import { useTranslations } from "next-intl";

import { APPROVAL_STATUS_TONE } from "@/lib/studio/format";
import type { ApprovalStatus } from "@/lib/studio/types";

export function ApprovalStatusBadge({ status }: { status: ApprovalStatus }) {
  const t = useTranslations("approvals.status");
  const tone = APPROVAL_STATUS_TONE[status] ?? "neutral";
  return (
    <Badge tone={tone}>
      <StatusDot tone={tone} />
      {t(status)}
    </Badge>
  );
}

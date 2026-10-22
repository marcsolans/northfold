"use client";

import { Badge, StatusDot } from "@messer/ui";
import { ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { DEPLOYMENT_STATUSES, type DeploymentStatus, isActive, statusTone } from "./types";

export function useEnvironmentLabel() {
  const t = useTranslations("deployments.environments");
  return React.useCallback((name: string) => (t.has(`${name}.label`) ? t(`${name}.label`) : name), [t]);
}

export function useStatusLabel() {
  const t = useTranslations("deployments.status");
  return React.useCallback(
    (status: string) => (DEPLOYMENT_STATUSES.includes(status as DeploymentStatus) ? t(status) : status),
    [t],
  );
}

export function DeploymentStatusBadge({ status, className }: { status: string; className?: string }) {
  const label = useStatusLabel();
  const tone = statusTone(status);
  return (
    <Badge tone={tone} className={className}>
      <StatusDot tone={tone} pulse={isActive(status)} />
      {label(status)}
    </Badge>
  );
}

export function ForcedBadge() {
  const t = useTranslations("deployments");
  return (
    <Badge tone="warning" title={t("forcedHint")}>
      <ShieldAlert className="size-3" aria-hidden />
      {t("forced")}
    </Badge>
  );
}

"use client";

import { Badge, Button, Popover, PopoverContent, PopoverTrigger, StatusDot, Tooltip, toast } from "@messer/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Rocket } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { localeTag } from "@/lib/format";

import { interfaceKeys } from "../api";
import type { Deployment } from "../types";
import { messageOf } from "../util";

const ACTIVE = ["pending", "evaluating", "deploying"];
const TONE: Record<string, "success" | "warning" | "danger" | "neutral" | "info"> = {
  live: "success",
  failed: "danger",
  pending: "info",
  evaluating: "info",
  deploying: "info",
  superseded: "neutral",
  rolled_back: "neutral",
};

/**
 * Publish = deploy the project to production (`POST /projects/{id}/deployments`). The pipeline runs the evals as a
 * gate and, when the version goes live, snapshots every interface. Saves pending changes first.
 */
export function PublishButton({
  projectId,
  interfaceId,
  dirty,
  canPublish,
  onSaveFirst,
}: {
  projectId: string;
  interfaceId: string;
  dirty: boolean;
  canPublish: boolean;
  onSaveFirst: () => Promise<boolean>;
}) {
  const t = useTranslations("interfaces.publish");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const [deploymentId, setDeploymentId] = React.useState<string | null>(null);
  const [unavailable, setUnavailable] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  const deployment = useQuery({
    queryKey: ["deployments", deploymentId],
    queryFn: () => http.get<Deployment>(`/deployments/${deploymentId}`),
    enabled: Boolean(deploymentId),
    refetchInterval: (q) => (q.state.data && !ACTIVE.includes(q.state.data.status) ? false : 2000),
  });
  const status = deployment.data?.status ?? null;
  const running = status !== null && ACTIVE.includes(status);

  const notified = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!deployment.data || ACTIVE.includes(deployment.data.status) || notified.current === deployment.data.id) return;
    notified.current = deployment.data.id;
    if (deployment.data.status === "live") toast.success(t("live"));
    else toast.error(t("failed"));
    void qc.invalidateQueries({ queryKey: interfaceKeys.detail(interfaceId) });
    void qc.invalidateQueries({ queryKey: interfaceKeys.list(projectId) });
  }, [deployment.data, interfaceId, projectId, qc, t]);

  const publish = async () => {
    setBusy(true);
    try {
      if (dirty && !(await onSaveFirst())) return;
      const dep = await http.post<Deployment>(`/projects/${projectId}/deployments`, { environment: "production", version_id: null, force: false, message: t("message") });
      notified.current = null;
      setDeploymentId(dep.id);
      setOpen(true);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 405)) setUnavailable(true);
      else toast.error(messageOf(err, t("failed")));
    } finally {
      setBusy(false);
    }
  };

  if (unavailable || !canPublish) {
    return (
      <Tooltip content={unavailable ? t("unavailable") : t("noPermission")}>
        <span tabIndex={0}>
          <Button variant="primary" disabled>
            <Rocket />
            {t("publish")}
          </Button>
        </span>
      </Tooltip>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <Button variant="primary" loading={busy || running} onClick={() => void publish()}>
        <Rocket />
        {running ? t("publishing") : dirty ? t("saveAndPublish") : t("publish")}
      </Button>
      {deployment.data ? (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <button type="button" className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-fg-muted hover:bg-subtle" aria-label={t("details")}>
              <StatusDot tone={TONE[deployment.data.status] ?? "neutral"} pulse={running} />
              {t(`status.${deployment.data.status}`)}
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-96 p-0">
            <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
              <p className="text-sm font-semibold">{t("title")}</p>
              <Badge tone={TONE[deployment.data.status] ?? "neutral"}>{t(`status.${deployment.data.status}`)}</Badge>
            </div>
            <ol className="max-h-64 overflow-auto px-3 py-2 text-xs">
              {deployment.data.logs.map((l, i) => (
                <li key={i} className="flex gap-2 py-0.5">
                  <span className="tabular shrink-0 text-fg-subtle">{new Intl.DateTimeFormat(locale, { timeStyle: "medium" }).format(new Date(l.at))}</span>
                  <span className={l.level === "error" ? "text-danger" : l.level === "warning" ? "text-warning" : "text-fg"}>{l.message}</span>
                </li>
              ))}
            </ol>
            <div className="border-t border-border px-3 py-2 text-right">
              <Link href={`/app/projects/${projectId}/deployments`} className="text-xs font-medium text-accent underline-offset-4 hover:underline">
                {t("history")}
              </Link>
            </div>
          </PopoverContent>
        </Popover>
      ) : null}
    </div>
  );
}

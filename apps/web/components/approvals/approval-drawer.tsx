"use client";

import { Alert, Badge, ErrorState, Sheet, SkeletonRows, toast } from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { traceHref, useChannelLabel } from "@/components/traces/runs-table";
import { ApiError, http } from "@/lib/api";
import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { errorMessage } from "@/lib/studio/hooks";
import type { Approval, Decision, DecisionBody } from "@/lib/studio/types";

import { ApprovalStatusBadge } from "./approval-status-badge";
import { DecisionPanel } from "./decision-panel";
import { PayloadView } from "./payload-view";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2 py-1.5 text-sm">
      <dt className="text-fg-subtle">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export function ApprovalDrawer({ approvalId, onClose }: { approvalId: string | null; onClose: () => void }) {
  const t = useTranslations("approvals.detail");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const channelLabel = useChannelLabel();
  const [busy, setBusy] = React.useState<Decision | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const approval = useQuery({
    queryKey: ["approvals", "detail", approvalId],
    queryFn: () => http.get<Approval>(`/approvals/${approvalId}`),
    enabled: approvalId !== null,
  });

  React.useEffect(() => {
    setError(null);
    setBusy(null);
  }, [approvalId]);

  const decide = useMutation({
    mutationFn: (body: DecisionBody) => http.post<Approval>(`/approvals/${approvalId}/decision`, body as unknown as Record<string, unknown>),
    onMutate: (body) => {
      setBusy(body.decision);
      setError(null);
    },
    onSuccess: (updated) => {
      qc.setQueryData(["approvals", "detail", approvalId], updated);
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      void qc.invalidateQueries({ queryKey: ["notifications"] });
      toast.success(updated.status === "approved" ? t("approvedToast") : t("deniedToast"));
    },
    onError: (err) => {
      setError(errorMessage(err, tc("errorGeneric")));
      if (err instanceof ApiError && err.status === 409) void approval.refetch();
    },
    onSettled: () => setBusy(null),
  });

  const a = approval.data;
  const expired = a?.status === "pending" && a.expires_at !== null && new Date(a.expires_at).getTime() <= Date.now();

  return (
    <Sheet
      open={approvalId !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={a?.title || t("title")}
      description={a ? `${a.project_name ?? "—"} · ${a.workforce_name} · ${a.tool_name}` : undefined}
    >
      {approval.isLoading ? (
        <SkeletonRows rows={6} />
      ) : approval.error || !a ? (
        <ErrorState title={tc("errorTitle")} description={errorMessage(approval.error, tc("errorGeneric"))} onRetry={() => void approval.refetch()} retryLabel={tc("retry")} />
      ) : (
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap items-center gap-2">
            <ApprovalStatusBadge status={a.status} />
            <Badge tone="outline" className="font-mono">
              {a.tool_name}
            </Badge>
            <Badge tone="outline">{t("assignedTo", { role: tc(`roles.${a.assigned_role}`) })}</Badge>
          </div>

          <section>
            <h3 className="mb-2 text-sm font-semibold">{t("payload")}</h3>
            <PayloadView payload={a.payload} schema={a.input_schema} changes={a.corrected_payload} />
          </section>

          {a.context_summary ? (
            <section>
              <h3 className="mb-2 text-sm font-semibold">{t("context")}</h3>
              <blockquote className="whitespace-pre-wrap border-l-2 border-border-strong pl-3 text-sm text-fg-muted">{a.context_summary}</blockquote>
            </section>
          ) : null}

          <section>
            <h3 className="mb-1 text-sm font-semibold">{t("details")}</h3>
            <dl className="divide-y divide-border">
              <Row label={t("project")}>
                <Link href={`/app/projects/${a.project_id}`} className="hover:underline">
                  {a.project_name ?? a.project_id}
                </Link>
              </Row>
              <Row label={t("agent")}>
                <Link href={`/app/projects/${a.project_id}/agents/${encodeURIComponent(a.workforce_name)}`} className="font-mono text-xs hover:underline">
                  {a.workforce_name}
                </Link>
              </Row>
              <Row label={t("run")}>
                <Link href={traceHref(a.project_id, a.run_id)} className="hover:underline">
                  {t("viewTrace")}
                </Link>
                {a.resume_run_id ? (
                  <>
                    {" · "}
                    <Link href={traceHref(a.project_id, a.resume_run_id)} className="hover:underline">
                      {t("viewResumed")}
                    </Link>
                  </>
                ) : null}
              </Row>
              <Row label={t("environment")}>{a.environment}</Row>
              {a.channel ? <Row label={t("channel")}>{channelLabel(a.channel)}</Row> : null}
              <Row label={t("created")}>{formatDate(a.created_at, locale, true)}</Row>
              {a.expires_at ? (
                <Row label={t("expires")}>
                  {formatDate(a.expires_at, locale, true)}{" "}
                  <span className="text-fg-subtle">({t(`expiryAction.${a.expiry_action === "approve" ? "approve" : "deny"}`)})</span>
                </Row>
              ) : null}
              {a.decided_at ? (
                <Row label={t("decided")}>
                  {formatRelative(a.decided_at, locale)}
                  {a.decision_via ? <span className="text-fg-subtle"> · {t.has(`via.${a.decision_via}`) ? t(`via.${a.decision_via}`) : a.decision_via}</span> : null}
                </Row>
              ) : null}
              {a.comment ? <Row label={t("comment")}>{a.comment}</Row> : null}
            </dl>
          </section>

          {a.status === "pending" ? (
            <section className="rounded-md border border-border p-3">
              <h3 className="mb-3 text-sm font-semibold">{t("decide")}</h3>
              {expired ? (
                <Alert tone="warning">{t("expiredPending")}</Alert>
              ) : (
                <DecisionPanel
                  key={a.id}
                  idPrefix={`inbox-${a.id}`}
                  payload={a.payload}
                  schema={a.input_schema}
                  canDecide={a.can_decide}
                  assignedRole={a.assigned_role}
                  busy={busy}
                  error={error}
                  onDecide={(body) => decide.mutate(body)}
                />
              )}
            </section>
          ) : null}
        </div>
      )}
    </Sheet>
  );
}

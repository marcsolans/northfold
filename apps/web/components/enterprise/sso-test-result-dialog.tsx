"use client";

import { Alert, Badge, Button, Dialog, DialogContent, ErrorState, SkeletonRows } from "@messer/ui";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { ApiError, http } from "@/lib/api";

import type { SsoTestResult } from "./types";

export function SsoTestResultDialog({ resultKey, onClose }: { resultKey: string | null; onClose: () => void }) {
  const t = useTranslations("enterprise.sso.testResult");
  const tc = useTranslations("common");
  const result = useQuery({
    queryKey: ["sso", "test-result", resultKey],
    queryFn: () => http.get<SsoTestResult>(`/sso/test-results/${resultKey}`),
    enabled: Boolean(resultKey),
    retry: false,
  });
  const data = result.data;
  const expired = result.error instanceof ApiError && result.error.status === 404;

  return (
    <Dialog open={resultKey !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title={t("title")}
        footer={
          <Button variant="primary" onClick={onClose}>
            {tc("close")}
          </Button>
        }
      >
        {result.isLoading ? (
          <SkeletonRows rows={4} />
        ) : expired ? (
          <Alert tone="warning">{t("expired")}</Alert>
        ) : result.error || !data ? (
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void result.refetch()} />
        ) : (
          <div className="flex flex-col gap-3 text-sm">
            <Alert tone={data.ok ? "success" : "danger"} title={data.ok ? t("ok") : t("failed")}>
              {data.problems.length > 0 ? (
                <ul className="mt-1 list-disc pl-4">
                  {data.problems.map((p) => (
                    <li key={p.code}>
                      {p.message} <code className="font-mono text-xs">({p.code})</code>
                    </li>
                  ))}
                </ul>
              ) : null}
            </Alert>
            {data.identity ? (
              <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-2">
                <dt className="text-fg-muted">{t("email")}</dt>
                <dd className="break-all">{data.identity.email}</dd>
                <dt className="text-fg-muted">{t("subject")}</dt>
                <dd className="break-all font-mono text-xs">{data.identity.subject}</dd>
                <dt className="text-fg-muted">{t("groups")}</dt>
                <dd className="flex flex-wrap gap-1">
                  {data.identity.groups.length === 0 ? (
                    <span className="text-fg-subtle">{t("noGroups")}</span>
                  ) : (
                    data.identity.groups.map((g) => (
                      <Badge key={g} tone={data.matched_groups?.includes(g) ? "accent" : "neutral"}>
                        {g}
                      </Badge>
                    ))
                  )}
                </dd>
                {data.role ? (
                  <>
                    <dt className="text-fg-muted">{t("role")}</dt>
                    <dd>{tc(`roles.${data.role}`)}</dd>
                  </>
                ) : null}
                <dt className="text-fg-muted">{t("account")}</dt>
                <dd>{data.user_exists ? t("userExists") : t("newUser")}</dd>
              </dl>
            ) : null}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

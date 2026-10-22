"use client";

import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CodeBlock,
  ConfirmDialog,
  CopyButton,
  ErrorState,
  Field,
  Input,
  SkeletonRows,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, RotateCcw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";

import { connectorKeys, errorMessage } from "./queries";
import type { WebhookEvent, WebhookInfo } from "./types";

export function WebhookPanel({ connectionId }: { connectionId: string }) {
  const t = useTranslations("connectors.webhook");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const canRotate = useRole("admin");
  const [reveal, setReveal] = React.useState(false);
  const [rotating, setRotating] = React.useState(false);
  const info = useQuery({
    queryKey: connectorKeys.webhook(connectionId),
    queryFn: () => http.get<WebhookInfo>(`/connections/${connectionId}/webhook`),
  });
  const events = useQuery({
    queryKey: connectorKeys.webhookEvents(connectionId),
    queryFn: async () =>
      (await http.post<{ result: WebhookEvent[] }>(`/connections/${connectionId}/actions/list_events`, { args: { limit: 20 } })).result,
    refetchInterval: 10_000,
  });
  const rotate = useMutation({
    mutationFn: () => http.post<{ url: string; secret: string }>(`/connections/${connectionId}/webhook/rotate`),
    onSuccess: () => {
      toast.success(t("rotated"));
      setRotating(false);
      setReveal(true);
      void qc.invalidateQueries({ queryKey: connectorKeys.webhook(connectionId) });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  if (info.isLoading) return <SkeletonRows rows={3} />;
  if (info.error || !info.data) {
    return <ErrorState title={tc("errorTitle")} description={errorMessage(info.error)} onRetry={() => void info.refetch()} retryLabel={tc("retry")} />;
  }
  const w = info.data;
  const example =
    w.verification === "hmac"
      ? [
          `BODY='{"event":"invoice.paid","invoice":"F-2026-0412"}'`,
          `SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | sed 's/^.* //')`,
          `curl -X POST "${w.url}" -H "Content-Type: application/json" -H "${w.signature_header}: sha256=$SIG" -d "$BODY"`,
        ].join("\n")
      : `curl -X POST "${w.url}" -H "Content-Type: application/json" -H "X-Messer-Token: $SECRET" -d '{"event":"invoice.paid"}'`;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader
          title={t("url")}
          actions={
            canRotate ? (
              <Button size="sm" variant="secondary" onClick={() => setRotating(true)}>
                <RotateCcw />
                {t("rotate")}
              </Button>
            ) : null
          }
        />
        <CardBody className="flex flex-col gap-3">
          <Field label={t("url")}>
            <div className="flex items-center gap-1">
              <Input readOnly value={w.url} className="font-mono text-xs" aria-label={t("url")} />
              <CopyButton value={w.url} label={tc("copy")} />
            </div>
          </Field>
          <Field label={t("secret")}>
            <div className="flex items-center gap-1">
              <Input readOnly type={reveal ? "text" : "password"} value={w.secret} className="font-mono text-xs" aria-label={t("secret")} />
              <Button variant="ghost" size="icon-sm" onClick={() => setReveal((v) => !v)} aria-label={reveal ? t("hide") : t("reveal")}>
                {reveal ? <EyeOff /> : <Eye />}
              </Button>
              <CopyButton value={w.secret} label={tc("copy")} />
            </div>
          </Field>
          <div className="flex flex-col gap-2 text-sm text-fg-muted">
            <p className="font-medium text-fg">{t("howTo")}</p>
            <p>
              {w.verification === "hmac"
                ? t("howToBody", { header: w.signature_header, timestamp: w.timestamp_header })
                : t("howToToken")}
            </p>
            <CodeBlock code={example} language="bash" />
          </div>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t("recent")} />
        <CardBody>
          {events.isLoading ? (
            <SkeletonRows rows={3} />
          ) : events.error ? (
            <ErrorState title={tc("errorTitle")} description={errorMessage(events.error)} onRetry={() => void events.refetch()} retryLabel={tc("retry")} />
          ) : (events.data ?? []).length === 0 ? (
            <p className="text-sm text-fg-subtle">{t("noEvents")}</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {(events.data ?? []).map((e) => (
                <li key={e.id} className="flex flex-col gap-1">
                  <span className="text-xs text-fg-subtle">
                    {t("received")} {e.occurred_at ? formatDate(e.occurred_at, locale, true) : ""} · {e.data.source_ip ?? ""}
                  </span>
                  <CodeBlock code={JSON.stringify(e.data.payload, null, 2)} language="json" className="max-h-48 overflow-auto" />
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
      <ConfirmDialog
        open={rotating}
        onOpenChange={setRotating}
        title={t("rotateTitle")}
        description={t("rotateDescription")}
        confirmLabel={t("rotate")}
        cancelLabel={tc("cancel")}
        loading={rotate.isPending}
        onConfirm={() => rotate.mutate()}
      />
    </div>
  );
}

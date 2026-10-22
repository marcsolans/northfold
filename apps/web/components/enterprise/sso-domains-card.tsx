"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  CopyButton,
  ErrorState,
  Input,
  SkeletonRows,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";

import type { OrgDomain } from "./types";

export function SsoDomainsCard() {
  const t = useTranslations("enterprise.domains");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const domains = useQuery({ queryKey: ["sso", "domains"], queryFn: () => http.get<OrgDomain[]>("/sso/domains") });
  const [value, setValue] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [removing, setRemoving] = React.useState<OrgDomain | null>(null);

  const refresh = () => void qc.invalidateQueries({ queryKey: ["sso"] });
  const fail = (err: unknown) => setError(err instanceof ApiError ? err.message : String(err));
  const add = useMutation({
    mutationFn: () => http.post<OrgDomain>("/sso/domains", { domain: value.trim() }),
    onSuccess: () => {
      setValue("");
      toast.success(t("added"));
      refresh();
    },
    onError: fail,
  });
  const verify = useMutation({
    mutationFn: (id: string) => http.post<OrgDomain>(`/sso/domains/${id}/verify`, {}),
    onSuccess: () => {
      toast.success(t("verifiedToast"));
      refresh();
    },
    onError: (err) => {
      fail(err);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => http.del(`/sso/domains/${id}`),
    onSuccess: () => {
      setRemoving(null);
      refresh();
    },
    onError: (err) => {
      setRemoving(null);
      fail(err);
    },
  });

  return (
    <Card>
      <CardHeader title={t("title")} description={t("description")} />
      <div className="flex flex-col gap-3 p-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            if (value.trim()) add.mutate();
          }}
        >
          <Input
            aria-label={t("add")}
            placeholder={t("placeholder")}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="max-w-xs"
          />
          <Button type="submit" variant="secondary" loading={add.isPending}>
            {t("add")}
          </Button>
        </form>
        {domains.isLoading ? (
          <SkeletonRows rows={2} />
        ) : domains.error ? (
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void domains.refetch()} />
        ) : (domains.data ?? []).length === 0 ? (
          <p className="text-sm text-fg-subtle">{t("empty")}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
            {(domains.data ?? []).map((d) => (
              <li key={d.id} className="flex flex-col gap-2 px-3 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{d.domain}</span>
                    {d.verified_at ? (
                      <Badge tone="success">
                        <CheckCircle2 className="size-3" aria-hidden />
                        {t("verified")}
                      </Badge>
                    ) : (
                      <Badge tone="warning">{t("pending")}</Badge>
                    )}
                    {d.verified_at ? (
                      <span className="text-xs text-fg-subtle">{formatDate(d.verified_at, locale)}</span>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-1">
                    {!d.verified_at ? (
                      <Button size="sm" variant="dark" loading={verify.isPending && verify.variables === d.id} onClick={() => verify.mutate(d.id)}>
                        {t("verify")}
                      </Button>
                    ) : null}
                    <Button size="icon-sm" variant="ghost" aria-label={tc("delete")} onClick={() => setRemoving(d)}>
                      <Trash2 />
                    </Button>
                  </div>
                </div>
                {!d.verified_at ? (
                  <div className="grid gap-1 rounded-md bg-subtle p-2 text-xs sm:grid-cols-[6rem_1fr_auto] sm:items-center">
                    <span className="text-fg-subtle">{t("recordName")}</span>
                    <code className="break-all font-mono">{d.record.name}</code>
                    <CopyButton value={d.record.name} label={tc("copy")} />
                    <span className="text-fg-subtle">{t("recordValue")}</span>
                    <code className="break-all font-mono">{d.record.value}</code>
                    <CopyButton value={d.record.value} label={tc("copy")} />
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("removeConfirm", { domain: removing?.domain ?? "" })}
        description={t("removeDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.id);
        }}
      />
    </Card>
  );
}

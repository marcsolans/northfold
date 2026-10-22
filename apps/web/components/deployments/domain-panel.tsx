"use client";

import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  CopyButton,
  Field,
  Input,
  StatusDot,
  type StatusTone,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, Globe, Lock, RefreshCw, Trash2, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useUpgradeDialog } from "@/components/billing";
import { http } from "@/lib/api";
import { studioKeys } from "@/lib/studio/hooks";
import type { Environment } from "@/lib/studio/types";

import { useEnvironmentLabel } from "./labels";
import { useApiErrorText } from "./queries";
import { DOMAIN_PATTERN, type DnsRecord, type DomainStatus, type DomainView } from "./types";

type ShownStatus = DomainStatus | "unverified";

const DOMAIN_TONE: Record<ShownStatus, StatusTone> = {
  pending: "warning",
  unverified: "warning",
  verified: "info",
  active: "success",
  failed: "danger",
};

function recordCheck(record: DnsRecord, checks: DomainView["checks"]): boolean | null {
  if (!checks) return null;
  if (record.type === "TXT") return checks.txt;
  if (record.type === "CNAME") return checks.cname;
  return null;
}

/**
 * Custom domain of one environment: add a domain → DNS records to create (with copy buttons) → "Verificar" with a
 * per-record result → active (automatic TLS certificate). Only admins can change it; everyone else sees the state.
 */
export function DomainPanel({ projectId, environment, canManage }: { projectId: string; environment: Environment; canManage: boolean }) {
  const t = useTranslations("deployments.domain");
  const tc = useTranslations("common");
  const envLabel = useEnvironmentLabel();
  const errorText = useApiErrorText();
  const qc = useQueryClient();
  const upgrade = useUpgradeDialog();

  const [input, setInput] = React.useState("");
  const [touched, setTouched] = React.useState(false);
  const [view, setView] = React.useState<DomainView | null>(null);
  const [removeOpen, setRemoveOpen] = React.useState(false);

  const domain = environment.custom_domain;
  const known = view && view.domain === domain ? view : null;
  const status: ShownStatus | null = !domain
    ? null
    : (known?.status ?? (environment.url === `https://${domain}` ? "active" : "unverified"));

  /** Apply the answer to the cached environment at once, then refetch. */
  const refreshEnvironments = (patch?: Partial<Environment>) => {
    if (patch) {
      qc.setQueryData(studioKeys.environments(projectId), (prev: Environment[] | undefined) =>
        prev?.map((e) => (e.id === environment.id ? { ...e, ...patch } : e)),
      );
    }
    void qc.invalidateQueries({ queryKey: studioKeys.environments(projectId) });
  };
  const base = `/projects/${projectId}/environments/${environment.name}/domain`;

  const save = useMutation({
    mutationFn: (value: string) => http.put<DomainView>(base, { domain: value }),
    onSuccess: (data) => {
      setView(data);
      setInput("");
      setTouched(false);
      refreshEnvironments({ custom_domain: data.domain });
      toast.success(t("added", { domain: data.domain ?? "" }));
    },
    onError: (err) => {
      if (!upgrade.handle(err)) toast.error(errorText(err));
    },
  });

  const verify = useMutation({
    mutationFn: () => http.post<DomainView>(`${base}/verify`),
    onSuccess: (data) => {
      setView(data);
      refreshEnvironments(data.status === "active" && data.url ? { url: data.url } : undefined);
      if (data.status === "active") toast.success(t("verifiedActive", { domain: data.domain ?? "" }));
      else if (data.status === "verified") toast.message(t("verifiedOwnership"));
      else toast.message(t("notYet"));
    },
    onError: (err) => {
      if (!upgrade.handle(err)) toast.error(errorText(err));
    },
  });

  const remove = useMutation({
    mutationFn: () => http.del(base),
    onSuccess: () => {
      setRemoveOpen(false);
      setView(null);
      refreshEnvironments({ custom_domain: null });
      toast.success(t("removed"));
    },
    onError: (err) => {
      if (!upgrade.handle(err)) toast.error(errorText(err));
    },
  });

  const normalized = input.trim().toLowerCase().replace(/\.$/, "").replace(/^https?:\/\//, "");
  const inputError = touched && normalized && !DOMAIN_PATTERN.test(normalized) ? t("invalid") : null;
  const headingId = `domain-${environment.id}`;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Globe className="size-4 text-fg-subtle" aria-hidden />
        <h4 id={headingId} className="text-sm font-semibold">
          {t("title")}
        </h4>
        {status ? (
          <Badge tone={DOMAIN_TONE[status]}>
            <StatusDot tone={DOMAIN_TONE[status]} />
            {t(`status.${status}`)}
          </Badge>
        ) : null}
      </div>

      {!domain ? (
        canManage ? (
          <form
            className="flex flex-col gap-2"
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              setTouched(true);
              if (normalized && DOMAIN_PATTERN.test(normalized)) save.mutate(normalized);
            }}
          >
            <Field
              label={t("inputLabel", { environment: envLabel(environment.name) })}
              htmlFor={`domain-input-${environment.id}`}
              error={inputError}
              hint={t("inputHint")}
            >
              <div className="flex gap-2">
                <Input
                  id={`domain-input-${environment.id}`}
                  value={input}
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={t("placeholder")}
                  aria-invalid={Boolean(inputError)}
                  onChange={(e) => setInput(e.target.value)}
                  onBlur={() => setTouched(true)}
                />
                <Button type="submit" loading={save.isPending} disabled={!normalized}>
                  {t("add")}
                </Button>
              </div>
            </Field>
          </form>
        ) : (
          <p className="text-sm text-fg-muted">{t("none")} {t("adminOnly")}</p>
        )
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="break-all font-mono text-sm">{domain}</span>
            {status === "active" ? (
              <a
                href={`https://${domain}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
              >
                {t("open")}
                <ExternalLink className="size-3" aria-hidden />
              </a>
            ) : null}
          </div>

          {status === "active" ? (
            <p className="flex items-start gap-1.5 text-xs text-fg-muted">
              <Lock className="mt-px size-3.5 shrink-0 text-success" aria-hidden />
              {t("activeHint")}
            </p>
          ) : known && known.dns.length > 0 ? (
            <div className="flex flex-col gap-2">
              <p className="text-xs text-fg-muted">{status === "verified" ? t("cnamePending") : t("recordsHint")}</p>
              <Table aria-label={t("recordsLabel", { domain })}>
                <THead>
                  <tr>
                    <TH>{t("type")}</TH>
                    <TH>{t("name")}</TH>
                    <TH>{t("value")}</TH>
                    <TH className="text-right">{t("check")}</TH>
                  </tr>
                </THead>
                <TBody>
                  {known.dns.map((record) => {
                    const ok = recordCheck(record, known.checks);
                    return (
                      <TR key={`${record.type}-${record.name}`}>
                        <TD className="font-mono text-xs font-medium">{record.type}</TD>
                        <TD>
                          <span className="flex items-center gap-1">
                            <span className="break-all font-mono text-xs">{record.name}</span>
                            <CopyButton value={record.name} label={t("copyName", { type: record.type })} />
                          </span>
                        </TD>
                        <TD>
                          <span className="flex items-center gap-1">
                            <span className="break-all font-mono text-xs">{record.value}</span>
                            <CopyButton value={record.value} label={t("copyValue", { type: record.type })} />
                          </span>
                        </TD>
                        <TD className="text-right">
                          {ok === null ? (
                            <span className="text-xs text-fg-subtle">{t("notChecked")}</span>
                          ) : ok ? (
                            <Badge tone="success">
                              <CheckCircle2 className="size-3" aria-hidden />
                              {t("found")}
                            </Badge>
                          ) : (
                            <Badge tone="danger">
                              <XCircle className="size-3" aria-hidden />
                              {t("missing")}
                            </Badge>
                          )}
                        </TD>
                      </TR>
                    );
                  })}
                </TBody>
              </Table>
              {known.checks && !(known.checks.txt && known.checks.cname) ? (
                <Alert tone="warning">{t("propagation")}</Alert>
              ) : null}
            </div>
          ) : (
            <p className="text-xs text-fg-muted">{canManage ? t("verifyToSeeRecords") : t("pendingViewer")}</p>
          )}

          {canManage ? (
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant={status === "active" ? "secondary" : "primary"}
                loading={verify.isPending}
                onClick={() => verify.mutate()}
              >
                <RefreshCw />
                {status === "active" ? t("recheck") : t("verify")}
              </Button>
              <Button size="sm" variant="danger" onClick={() => setRemoveOpen(true)}>
                <Trash2 />
                {t("remove")}
              </Button>
            </div>
          ) : (
            <p className="text-xs text-fg-subtle">{t("adminOnly")}</p>
          )}
        </div>
      )}

      <ConfirmDialog
        open={removeOpen}
        onOpenChange={setRemoveOpen}
        title={t("removeTitle", { domain: domain ?? "" })}
        description={t("removeDescription", { environment: envLabel(environment.name) })}
        confirmLabel={t("remove")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
      {upgrade.dialog}
    </section>
  );
}

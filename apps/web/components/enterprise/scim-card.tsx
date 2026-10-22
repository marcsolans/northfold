"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  CodeBlock,
  ConfirmDialog,
  CopyButton,
  Dialog,
  DialogContent,
  ErrorState,
  Field,
  Input,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, KeyRound } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { PlanLimitNotice, billingHref } from "@/components/billing";
import { ApiError, http } from "@/lib/api";
import { formatDate, formatRelative, localeTag } from "@/lib/format";

import type { ScimToken, ScimUser, SsoOverview } from "./types";

export function ScimCard({ overview }: { overview: SsoOverview }) {
  const t = useTranslations("enterprise.scim");
  const te = useTranslations("enterprise");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const tokens = useQuery({ queryKey: ["sso", "scim", "tokens"], queryFn: () => http.get<ScimToken[]>("/sso/scim/tokens") });
  const users = useQuery({ queryKey: ["sso", "scim", "users"], queryFn: () => http.get<ScimUser[]>("/sso/scim/users") });
  const [createOpen, setCreateOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [created, setCreated] = React.useState<string | null>(null);
  const [revoking, setRevoking] = React.useState<ScimToken | null>(null);

  const create = useMutation({
    mutationFn: () => http.post<ScimToken & { token: string }>("/sso/scim/tokens", { name: name.trim() || "SCIM" }),
    onSuccess: (res) => {
      setCreated(res.token);
      setName("");
      void qc.invalidateQueries({ queryKey: ["sso", "scim", "tokens"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => http.del(`/sso/scim/tokens/${id}`),
    onSuccess: () => {
      setRevoking(null);
      void qc.invalidateQueries({ queryKey: ["sso", "scim", "tokens"] });
    },
  });

  return (
    <Card>
      <CardHeader
        title={t("title")}
        description={t("description")}
        actions={
          overview.scim_available ? (
            <Button
              variant="secondary"
              onClick={() => {
                setCreated(null);
                create.reset();
                setCreateOpen(true);
              }}
            >
              <KeyRound />
              {t("newToken")}
            </Button>
          ) : null
        }
      />
      <div className="flex flex-col gap-4 p-4">
        {!overview.scim_available ? (
          <Alert
            tone="warning"
            title={te("upgrade.title")}
            action={
              <Button asChild size="sm" variant="dark">
                <Link href={billingHref(overview.scim_upgrade_to)}>
                  {te("upgrade.seePlans")}
                  <ArrowUpRight />
                </Link>
              </Button>
            }
          >
            {te("upgrade.scim")}
          </Alert>
        ) : null}
        <Field label={t("baseUrl")}>
          <div className="flex items-center gap-1 rounded-md border border-border bg-subtle px-2.5 py-1.5">
            <code className="min-w-0 flex-1 break-all font-mono text-xs">{overview.scim_base_url}</code>
            <CopyButton value={overview.scim_base_url} label={tc("copy")} />
          </div>
        </Field>

        <div>
          <p className="mb-2 text-sm font-medium">{t("tokens")}</p>
          {tokens.isLoading ? (
            <SkeletonRows rows={2} />
          ) : tokens.error ? (
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void tokens.refetch()} />
          ) : (tokens.data ?? []).length === 0 ? (
            <p className="text-sm text-fg-subtle">{t("empty")}</p>
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{t("tokenName")}</TH>
                  <TH className="hidden sm:table-cell">{tc("created")}</TH>
                  <TH>{t("lastUsed")}</TH>
                  <TH>{tc("status")}</TH>
                  <TH className="w-24" />
                </tr>
              </THead>
              <TBody>
                {(tokens.data ?? []).map((tok) => (
                  <TR key={tok.id}>
                    <TD className="font-medium">{tok.name}</TD>
                    <TD className="hidden text-fg-muted sm:table-cell">{formatDate(tok.created_at, locale)}</TD>
                    <TD className="text-fg-muted">{tok.last_used_at ? formatRelative(tok.last_used_at, locale) : t("never")}</TD>
                    <TD>{tok.revoked_at ? <Badge tone="neutral">{t("revoked")}</Badge> : <Badge tone="success">{t("active")}</Badge>}</TD>
                    <TD className="text-right">
                      {!tok.revoked_at ? (
                        <Button variant="ghost" size="sm" onClick={() => setRevoking(tok)}>
                          {t("revoke")}
                        </Button>
                      ) : null}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </div>

        <div>
          <p className="mb-2 text-sm font-medium">{t("users")}</p>
          {users.isLoading ? (
            <SkeletonRows rows={2} />
          ) : users.error ? (
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void users.refetch()} />
          ) : (users.data ?? []).length === 0 ? (
            <p className="text-sm text-fg-subtle">{t("usersEmpty")}</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border rounded-md border border-border text-sm">
              {(users.data ?? []).map((u) => (
                <li key={u.user_id} className="flex items-center justify-between gap-2 px-3 py-2">
                  <span className="min-w-0 truncate">{u.email}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    {u.external_id ? <code className="hidden font-mono text-xs text-fg-subtle sm:inline">{u.external_id}</code> : null}
                    {u.active ? <Badge tone="success">{t("active")}</Badge> : <Badge tone="neutral">{t("inactive")}</Badge>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent title={t("newToken")} description={t("newTokenDescription")}>
          {created ? (
            <div className="flex flex-col gap-3">
              <Alert tone="warning">{t("tokenCreated")}</Alert>
              <CodeBlock code={created} />
              <div className="flex justify-end">
                <Button variant="primary" onClick={() => setCreateOpen(false)}>
                  {tc("close")}
                </Button>
              </div>
            </div>
          ) : (
            <form
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                create.mutate();
              }}
            >
              <PlanLimitNotice error={create.error} />
              {create.error && !(create.error instanceof ApiError && create.error.status === 402) ? (
                <Alert tone="danger">{create.error instanceof ApiError ? create.error.message : String(create.error)}</Alert>
              ) : null}
              <Field label={t("tokenName")} htmlFor="scim-token-name">
                <Input id="scim-token-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Okta" autoFocus />
              </Field>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="secondary" onClick={() => setCreateOpen(false)}>
                  {tc("cancel")}
                </Button>
                <Button type="submit" variant="primary" loading={create.isPending}>
                  {tc("create")}
                </Button>
              </div>
            </form>
          )}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => !open && setRevoking(null)}
        title={t("revokeConfirm", { name: revoking?.name ?? "" })}
        description={t("revokeDescription")}
        confirmLabel={t("revoke")}
        cancelLabel={tc("cancel")}
        loading={revoke.isPending}
        onConfirm={() => {
          if (revoking) revoke.mutate(revoking.id);
        }}
      />
    </Card>
  );
}

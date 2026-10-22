"use client";

import {
  Alert,
  Button,
  ConfirmDialog,
  ErrorState,
  Field,
  Input,
  Select,
  Sheet,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";

import { ASSIGNABLE_ROLES, type AssignableRole, type GroupMapping, type SsoConnection } from "./types";

export function SsoMappingsSheet({
  connection,
  onOpenChange,
}: {
  connection: SsoConnection | null;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("enterprise.mappings");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const id = connection?.id;
  const key = ["sso", "mappings", id];
  const mappings = useQuery({
    queryKey: key,
    queryFn: () => http.get<GroupMapping[]>(`/sso/connections/${id}/mappings`),
    enabled: Boolean(id),
  });
  const [group, setGroup] = React.useState("");
  const [role, setRole] = React.useState<AssignableRole>("builder");
  const [error, setError] = React.useState<string | null>(null);
  const [removing, setRemoving] = React.useState<GroupMapping | null>(null);

  React.useEffect(() => {
    setGroup("");
    setError(null);
  }, [id]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: key });
    void qc.invalidateQueries({ queryKey: ["sso", "connections"] });
  };
  const add = useMutation({
    mutationFn: () => http.post<GroupMapping>(`/sso/connections/${id}/mappings`, { external_group: group.trim(), role }),
    onSuccess: () => {
      setGroup("");
      refresh();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });
  const remove = useMutation({
    mutationFn: (mappingId: string) => http.del(`/sso/connections/${id}/mappings/${mappingId}`),
    onSuccess: () => {
      setRemoving(null);
      refresh();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  return (
    <Sheet
      open={connection !== null}
      onOpenChange={onOpenChange}
      title={t("title")}
      description={connection ? `${connection.name} · ${connection.domain}` : undefined}
    >
      <div className="flex flex-col gap-4">
        <p className="text-sm text-fg-muted">{t("description")}</p>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <form
          className="grid gap-3 sm:grid-cols-[1fr_10rem_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            if (group.trim()) add.mutate();
          }}
        >
          <Field label={t("group")} htmlFor="mapping-group" hint={t("groupHint")}>
            <Input id="mapping-group" value={group} onChange={(e) => setGroup(e.target.value)} maxLength={255} required />
          </Field>
          <Field label={t("role")}>
            <Select
              value={role}
              onValueChange={(v) => setRole(v as AssignableRole)}
              options={ASSIGNABLE_ROLES.map((r) => ({ value: r, label: tc(`roles.${r}`) }))}
            />
          </Field>
          <Button type="submit" variant="dark" loading={add.isPending} className="sm:mb-[1.375rem]">
            {t("add")}
          </Button>
        </form>
        {mappings.isLoading ? (
          <SkeletonRows rows={3} />
        ) : mappings.error ? (
          <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void mappings.refetch()} />
        ) : (mappings.data ?? []).length === 0 ? (
          <p className="rounded-md border border-dashed border-border-strong px-4 py-6 text-center text-sm text-fg-muted">{t("empty")}</p>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{t("group")}</TH>
                <TH>{t("role")}</TH>
                <TH className="w-12" />
              </tr>
            </THead>
            <TBody>
              {(mappings.data ?? []).map((m) => (
                <TR key={m.id}>
                  <TD className="break-all font-mono text-xs">{m.external_group}</TD>
                  <TD>{tc(`roles.${m.role}`)}</TD>
                  <TD className="text-right">
                    <Button variant="ghost" size="icon-sm" aria-label={tc("remove")} onClick={() => setRemoving(m)}>
                      <Trash2 />
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </div>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("removeConfirm", { group: removing?.external_group ?? "" })}
        confirmLabel={tc("remove")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.id);
        }}
      />
    </Sheet>
  );
}

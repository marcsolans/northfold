"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  Field,
  Input,
  RadioCards,
  Select,
  SkeletonRows,
  Switch,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Textarea,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, ShieldCheck, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";

import { errorMessage, kbKeys, useKbTables } from "./queries";
import { DOCUMENTS_TABLE, type GovernanceMode, type KbPolicy, type KnowledgeBase, POLICY_ROLES, type PolicyRole } from "./types";

const DOCUMENT_COLUMNS = ["content", "heading", "filename", "metadata"];
type MaskKind = "redact" | "hash" | "truncate";

interface Draft {
  id: string | null;
  table: string;
  role: PolicyRole;
  rowFilter: string;
  masks: { column: string; kind: MaskKind; n: number }[];
  tags: string;
  breakGlass: boolean;
  enabled: boolean;
}

function toDraft(p: KbPolicy | null, defaultTable: string): Draft {
  if (!p) {
    return { id: null, table: defaultTable, role: "viewer", rowFilter: "", masks: [], tags: "", breakGlass: false, enabled: true };
  }
  return {
    id: p.id,
    table: p.table,
    role: p.role,
    rowFilter: p.row_filter_sql ?? "",
    masks: Object.entries(p.masked_columns).map(([column, mode]) => {
      const [kind, n] = mode.split(":");
      return { column, kind: (kind as MaskKind) ?? "redact", n: Number(n ?? 4) || 4 };
    }),
    tags: p.compliance_tags.join(", "),
    breakGlass: p.break_glass,
    enabled: p.enabled,
  };
}

export function PoliciesTab({ kb, isAdmin }: { kb: KnowledgeBase; isAdmin: boolean }) {
  const t = useTranslations("knowledge.policies");
  const tg = useTranslations("knowledge.governance");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const tables = useKbTables(kb.id);
  const policies = useQuery({
    queryKey: kbKeys.policies(kb.id),
    queryFn: () => http.get<KbPolicy[]>(`/knowledge-bases/${kb.id}/policies`),
  });
  const [draft, setDraft] = React.useState<Draft | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [deleting, setDeleting] = React.useState<KbPolicy | null>(null);

  const setMode = useMutation({
    mutationFn: (mode: GovernanceMode) => http.patch<KnowledgeBase>(`/knowledge-bases/${kb.id}`, { governance_mode: mode }),
    onSuccess: (updated) => {
      toast.success(t("modeSaved", { mode: tg(updated.governance_mode) }));
      void qc.invalidateQueries({ queryKey: kbKeys.detail(kb.id), exact: true });
      void qc.invalidateQueries({ queryKey: kbKeys.all, exact: false });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const save = useMutation({
    mutationFn: (d: Draft) => {
      const body = {
        table: d.table,
        role: d.role,
        row_filter_sql: d.rowFilter.trim() || null,
        masked_columns: Object.fromEntries(
          d.masks.filter((m) => m.column).map((m) => [m.column, m.kind === "truncate" ? `truncate:${m.n}` : m.kind]),
        ),
        compliance_tags: d.tags
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        break_glass: d.breakGlass,
        enabled: d.enabled,
      };
      return d.id
        ? http.put<KbPolicy>(`/knowledge-bases/${kb.id}/policies/${d.id}`, body)
        : http.post<KbPolicy>(`/knowledge-bases/${kb.id}/policies`, body);
    },
    onSuccess: () => {
      toast.success(t("saved"));
      setDraft(null);
      void qc.invalidateQueries({ queryKey: kbKeys.policies(kb.id) });
    },
    onError: (err) => setFormError(errorMessage(err)),
  });
  const remove = useMutation({
    mutationFn: (p: KbPolicy) => http.del(`/knowledge-bases/${kb.id}/policies/${p.id}`),
    onSuccess: () => {
      toast.success(t("deleted"));
      setDeleting(null);
      void qc.invalidateQueries({ queryKey: kbKeys.policies(kb.id) });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const tableOptions = [
    ...(tables.data ?? []).map((tbl) => ({ value: tbl.name, label: tbl.name })),
    { value: DOCUMENTS_TABLE, label: t("documents") },
  ];
  const columnsFor = (table: string) =>
    table === DOCUMENTS_TABLE
      ? DOCUMENT_COLUMNS
      : [
          ...((tables.data ?? []).find((tbl) => tbl.name === table)?.primary_key.length ? [] : ["_row_id"]),
          ...((tables.data ?? []).find((tbl) => tbl.name === table)?.columns.map((c) => c.name) ?? []),
        ];
  const roleLabel = (role: string) => t(`roles.${role === "*" ? "all" : role}`);
  const describeMask = (mode: string) => {
    const [kind, n] = mode.split(":");
    return kind === "truncate" ? t("maskTruncateN", { n: n ?? "" }) : t(`masks.${kind ?? "redact"}`);
  };

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader title={t("modeTitle")} description={t("modeDescription")} />
        <div className="p-4">
          <RadioCards
            className="sm:grid-cols-3"
            value={kb.governance_mode}
            onValueChange={(v) => isAdmin && setMode.mutate(v as GovernanceMode)}
            options={(["off", "shadow", "enforce"] as const).map((m) => ({
              value: m,
              label: tg(m),
              description: tg(`hint.${m}`),
              disabled: !isAdmin || setMode.isPending,
            }))}
          />
          {!isAdmin ? <p className="mt-2 text-xs text-fg-subtle">{t("adminOnly")}</p> : null}
        </div>
      </Card>

      <Card>
        <CardHeader
          title={t("title")}
          description={t("description")}
          actions={
            isAdmin ? (
              <Button
                size="sm"
                variant="primary"
                onClick={() => {
                  setFormError(null);
                  setDraft(toDraft(null, tableOptions[0]?.value ?? DOCUMENTS_TABLE));
                }}
              >
                <Plus />
                {t("add")}
              </Button>
            ) : null
          }
        />
        {policies.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={3} />
          </div>
        ) : policies.error ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={errorMessage(policies.error)} onRetry={() => void policies.refetch()} retryLabel={tc("retry")} />
          </div>
        ) : (policies.data ?? []).length === 0 ? (
          <div className="p-4">
            <EmptyState icon={<ShieldCheck />} title={t("empty")} description={t("emptyHint")} />
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{t("table")}</TH>
                <TH>{t("role")}</TH>
                <TH>{t("rowFilter")}</TH>
                <TH>{t("maskedColumns")}</TH>
                <TH className="hidden lg:table-cell">{t("tags")}</TH>
                <TH className="w-20" />
              </tr>
            </THead>
            <TBody>
              {(policies.data ?? []).map((p) => (
                <TR key={p.id}>
                  <TD className="font-mono text-xs">{p.table === DOCUMENTS_TABLE ? t("documents") : p.table}</TD>
                  <TD>
                    <span className="flex items-center gap-1.5">
                      {roleLabel(p.role)}
                      {!p.enabled ? <Badge>{t("disabled")}</Badge> : null}
                      {p.break_glass ? <Badge tone="warning">{t("breakGlassShort")}</Badge> : null}
                    </span>
                  </TD>
                  <TD className="max-w-56 truncate font-mono text-xs" title={p.row_filter_sql ?? ""}>
                    {p.row_filter_sql ?? "—"}
                  </TD>
                  <TD className="text-xs">
                    {Object.entries(p.masked_columns).length === 0
                      ? "—"
                      : Object.entries(p.masked_columns)
                          .map(([c, m]) => `${c}: ${describeMask(m)}`)
                          .join(" · ")}
                  </TD>
                  <TD className="hidden lg:table-cell">
                    <span className="flex flex-wrap gap-1">
                      {p.compliance_tags.map((tag) => (
                        <Badge key={tag} tone="outline">
                          {tag}
                        </Badge>
                      ))}
                    </span>
                  </TD>
                  <TD className="text-right">
                    {isAdmin ? (
                      <span className="flex justify-end gap-1">
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          aria-label={tc("edit")}
                          onClick={() => {
                            setFormError(null);
                            setDraft(toDraft(p, p.table));
                          }}
                        >
                          <Pencil />
                        </Button>
                        <Button size="icon-sm" variant="ghost" aria-label={tc("delete")} onClick={() => setDeleting(p)}>
                          <Trash2 />
                        </Button>
                      </span>
                    ) : null}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <Dialog open={draft !== null} onOpenChange={(open) => !open && setDraft(null)}>
        <DialogContent wide title={draft?.id ? t("editTitle") : t("addTitle")} description={t("formDescription")}>
          {draft ? (
            <form
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                setFormError(null);
                save.mutate(draft);
              }}
            >
              {formError ? <Alert tone="danger">{formError}</Alert> : null}
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label={t("table")}>
                  <Select
                    value={draft.table}
                    onValueChange={(v) => setDraft({ ...draft, table: v, masks: [] })}
                    options={tableOptions}
                  />
                </Field>
                <Field label={t("role")}>
                  <Select
                    value={draft.role}
                    onValueChange={(v) => setDraft({ ...draft, role: v as PolicyRole })}
                    options={POLICY_ROLES.map((r) => ({ value: r, label: roleLabel(r), description: t(`roleHints.${r === "*" ? "all" : r}`) }))}
                  />
                </Field>
              </div>
              <Field
                label={t("rowFilter")}
                htmlFor="policy-filter"
                hint={draft.table === DOCUMENTS_TABLE ? t("rowFilterDocumentsHint") : t("rowFilterHint", { columns: columnsFor(draft.table).join(", ") })}
              >
                <Textarea
                  id="policy-filter"
                  className="font-mono text-xs"
                  rows={2}
                  value={draft.rowFilter}
                  placeholder={draft.table === DOCUMENTS_TABLE ? "filename NOT LIKE 'rrhh/%'" : "region = 'norte'"}
                  onChange={(e) => setDraft({ ...draft, rowFilter: e.target.value })}
                />
              </Field>
              <div className="flex flex-col gap-2">
                <p className="text-sm font-medium">{t("maskedColumns")}</p>
                {draft.masks.map((m, i) => (
                  <div key={i} className="flex flex-wrap items-center gap-2">
                    <Select
                      aria-label={t("column")}
                      className="w-48"
                      value={m.column}
                      onValueChange={(v) => setDraft({ ...draft, masks: draft.masks.map((x, j) => (j === i ? { ...x, column: v } : x)) })}
                      options={columnsFor(draft.table).map((c) => ({ value: c, label: c }))}
                    />
                    <Select
                      aria-label={t("mask")}
                      className="w-40"
                      value={m.kind}
                      onValueChange={(v) => setDraft({ ...draft, masks: draft.masks.map((x, j) => (j === i ? { ...x, kind: v as MaskKind } : x)) })}
                      options={(["redact", "hash", "truncate"] as const).map((k) => ({ value: k, label: t(`masks.${k}`), description: t(`maskHints.${k}`) }))}
                    />
                    {m.kind === "truncate" ? (
                      <Input
                        type="number"
                        min={1}
                        max={1000}
                        aria-label={t("truncateLength")}
                        className="w-20"
                        value={m.n}
                        onChange={(e) => setDraft({ ...draft, masks: draft.masks.map((x, j) => (j === i ? { ...x, n: Number(e.target.value) || 1 } : x)) })}
                      />
                    ) : null}
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      aria-label={tc("remove")}
                      onClick={() => setDraft({ ...draft, masks: draft.masks.filter((_, j) => j !== i) })}
                    >
                      <X />
                    </Button>
                  </div>
                ))}
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="self-start"
                  onClick={() => setDraft({ ...draft, masks: [...draft.masks, { column: columnsFor(draft.table)[0] ?? "", kind: "redact", n: 4 }] })}
                >
                  <Plus />
                  {t("addMask")}
                </Button>
              </div>
              <Field label={t("tags")} htmlFor="policy-tags" hint={t("tagsHint")}>
                <Input id="policy-tags" value={draft.tags} onChange={(e) => setDraft({ ...draft, tags: e.target.value })} placeholder="gdpr, pii" />
              </Field>
              <label className="flex items-start gap-2 text-sm">
                <Switch checked={draft.breakGlass} onCheckedChange={(v) => setDraft({ ...draft, breakGlass: v })} aria-label={t("breakGlass")} />
                <span>
                  <span className="font-medium">{t("breakGlass")}</span>
                  <span className="block text-xs text-fg-muted">{t("breakGlassHint")}</span>
                </span>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <Switch checked={draft.enabled} onCheckedChange={(v) => setDraft({ ...draft, enabled: v })} aria-label={t("enabled")} />
                {t("enabled")}
              </label>
              <div className="mt-2 flex justify-end gap-2">
                <Button type="button" variant="secondary" onClick={() => setDraft(null)}>
                  {tc("cancel")}
                </Button>
                <Button type="submit" variant="primary" loading={save.isPending} disabled={!draft.table}>
                  {tc("save")}
                </Button>
              </div>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("deleteConfirm")}
        description={t("deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting);
        }}
      />
    </div>
  );
}

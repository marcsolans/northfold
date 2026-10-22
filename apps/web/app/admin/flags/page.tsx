"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
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
import { Flag, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ADMIN_KEY, type AdminPlan, type FeatureFlag } from "@/components/admin/types";
import { errorText } from "@/components/billing";
import { ApiError, http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";

const FLAGS_KEY = [...ADMIN_KEY, "flags"] as const;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function FlagDialog({ flag, onClose }: { flag: FeatureFlag | "new" | null; onClose: () => void }) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const existing = flag === "new" ? null : flag;
  const plans = useQuery({ queryKey: [...ADMIN_KEY, "plans"], queryFn: () => http.get<AdminPlan[]>("/admin/plans") });
  const [key, setKey] = React.useState(existing?.key ?? "");
  const [description, setDescription] = React.useState(existing?.description ?? "");
  const [enabled, setEnabled] = React.useState(existing?.enabled ?? false);
  const [planIds, setPlanIds] = React.useState<string[]>(existing?.targeting.plans ?? []);
  const [orgIds, setOrgIds] = React.useState((existing?.targeting.orgs ?? []).join("\n"));
  const [error, setError] = React.useState<string | null>(null);
  const orgList = orgIds
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const badOrgs = orgList.filter((o) => !UUID_RE.test(o));
  const save = useMutation({
    mutationFn: () =>
      http.put<FeatureFlag>(`/admin/feature-flags/${encodeURIComponent(key.trim())}`, {
        description: description.trim(),
        enabled,
        targeting: { plans: planIds, orgs: orgList },
      }),
    onSuccess: () => {
      toast.success(t("flags.saved"));
      onClose();
      void qc.invalidateQueries({ queryKey: FLAGS_KEY });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });
  const valid = /^[a-z0-9][a-z0-9_.-]{1,78}$/.test(key.trim()) && badOrgs.length === 0;
  return (
    <Dialog open={flag !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={existing ? t("flags.editTitle", { key: existing.key }) : t("flags.newTitle")} description={t("flags.formDescription")}>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) save.mutate();
          }}
        >
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Field label={t("flags.key")} htmlFor="flag-key" hint={t("flags.keyHint")}>
            <Input id="flag-key" required disabled={Boolean(existing)} value={key} onChange={(e) => setKey(e.target.value)} />
          </Field>
          <Field label={tc("description")} htmlFor="flag-description">
            <Input id="flag-description" value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={enabled} onCheckedChange={setEnabled} aria-label={t("flags.enabled")} />
            {t("flags.enabled")}
          </label>
          <fieldset>
            <legend className="mb-1 text-sm font-medium">{t("flags.plans")}</legend>
            <p className="mb-2 text-xs text-fg-subtle">{t("flags.targetingHint")}</p>
            <div className="flex flex-wrap gap-4">
              {(plans.data ?? []).map((p) => (
                <label key={p.id} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={planIds.includes(p.id)}
                    onCheckedChange={(checked) =>
                      setPlanIds((ids) => (checked === true ? [...ids, p.id] : ids.filter((x) => x !== p.id)))
                    }
                  />
                  {p.name}
                </label>
              ))}
            </div>
          </fieldset>
          <Field
            label={t("flags.orgs")}
            htmlFor="flag-orgs"
            hint={t("flags.orgsHint")}
            error={badOrgs.length ? t("flags.badOrgs", { ids: badOrgs.join(", ") }) : undefined}
          >
            <Textarea id="flag-orgs" value={orgIds} onChange={(e) => setOrgIds(e.target.value)} className="font-mono text-xs" />
          </Field>
          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              {tc("cancel")}
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending} disabled={!valid}>
              {tc("save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function AdminFlagsPage() {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const flags = useQuery({ queryKey: FLAGS_KEY, queryFn: () => http.get<FeatureFlag[]>("/admin/feature-flags") });
  const [editing, setEditing] = React.useState<FeatureFlag | "new" | null>(null);
  const [deleting, setDeleting] = React.useState<FeatureFlag | null>(null);
  const toggle = useMutation({
    mutationFn: (flag: FeatureFlag) =>
      http.put<FeatureFlag>(`/admin/feature-flags/${encodeURIComponent(flag.key)}`, {
        description: flag.description,
        enabled: !flag.enabled,
        targeting: flag.targeting,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: FLAGS_KEY }),
    onError: (err) => toast.error(errorText(err)),
  });
  const remove = useMutation({
    mutationFn: (key: string) => http.del(`/admin/feature-flags/${encodeURIComponent(key)}`),
    onSuccess: () => {
      setDeleting(null);
      toast.success(t("flags.deleted"));
      void qc.invalidateQueries({ queryKey: FLAGS_KEY });
    },
    onError: (err) => toast.error(errorText(err)),
  });

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={t("flags.title")}
        description={t("flags.description")}
        actions={
          <Button variant="primary" onClick={() => setEditing("new")}>
            <Plus />
            {t("flags.new")}
          </Button>
        }
      />
      <Card>
        {flags.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={4} />
          </div>
        ) : flags.error || !flags.data ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void flags.refetch()} />
          </div>
        ) : flags.data.length === 0 ? (
          <div className="p-4">
            <EmptyState icon={<Flag />} title={t("flags.emptyTitle")} description={t("flags.empty")} />
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{t("flags.key")}</TH>
                <TH className="hidden md:table-cell">{t("flags.targeting")}</TH>
                <TH className="hidden lg:table-cell">{tc("updated")}</TH>
                <TH>{t("flags.enabled")}</TH>
                <TH className="w-32" />
              </tr>
            </THead>
            <TBody>
              {flags.data.map((f) => (
                <TR key={f.key}>
                  <TD>
                    <span className="font-mono text-sm">{f.key}</span>
                    <span className="block text-xs text-fg-subtle">{f.description}</span>
                  </TD>
                  <TD className="hidden md:table-cell">
                    {f.targeting.plans.length === 0 && f.targeting.orgs.length === 0 ? (
                      <span className="text-fg-muted">{t("flags.everyone")}</span>
                    ) : (
                      <span className="flex flex-wrap gap-1">
                        {f.targeting.plans.map((p) => (
                          <Badge key={p} tone="outline">
                            {p}
                          </Badge>
                        ))}
                        {f.targeting.orgs.length ? <Badge tone="outline">{t("flags.orgCount", { count: f.targeting.orgs.length })}</Badge> : null}
                      </span>
                    )}
                  </TD>
                  <TD className="hidden text-fg-muted lg:table-cell">{formatDate(f.updated_at, locale)}</TD>
                  <TD>
                    <Switch checked={f.enabled} aria-label={t("flags.enabled")} disabled={toggle.isPending} onCheckedChange={() => toggle.mutate(f)} />
                  </TD>
                  <TD className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="sm" onClick={() => setEditing(f)}>
                        {tc("edit")}
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setDeleting(f)}>
                        {tc("delete")}
                      </Button>
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      {editing !== null ? <FlagDialog key={editing === "new" ? "new" : editing.key} flag={editing} onClose={() => setEditing(null)} /> : null}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("flags.deleteTitle", { key: deleting?.key ?? "" })}
        description={t("flags.deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.key);
        }}
      />
    </div>
  );
}

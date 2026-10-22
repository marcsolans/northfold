"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
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
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ADMIN_KEY, type ModelPrice } from "@/components/admin/types";
import { errorText } from "@/components/billing";
import { ApiError, http } from "@/lib/api";
import { formatDate, formatNumber, formatUsd, localeTag } from "@/lib/format";

const PRICES_KEY = [...ADMIN_KEY, "model-prices"] as const;
const PRICE_FIELDS = ["input_per_mtok_usd", "output_per_mtok_usd", "cache_read_per_mtok_usd", "cache_write_per_mtok_usd"] as const;
type PriceField = (typeof PRICE_FIELDS)[number];

interface PriceForm {
  model: string;
  provider: string;
  display_name: string;
  context_window: string;
  active: boolean;
  prices: Record<PriceField, string>;
}

function toForm(p: ModelPrice | null): PriceForm {
  return {
    model: p?.model ?? "",
    provider: p?.provider ?? "anthropic",
    display_name: p?.display_name ?? "",
    context_window: p?.context_window ? String(p.context_window) : "",
    active: p?.active ?? true,
    prices: Object.fromEntries(PRICE_FIELDS.map((f) => [f, p ? String(Number(p[f])) : "0"])) as Record<PriceField, string>,
  };
}

function PriceDialog({ price, onClose }: { price: ModelPrice | null | "new"; onClose: () => void }) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const existing = price === "new" ? null : price;
  const [form, setForm] = React.useState<PriceForm>(() => toForm(existing));
  const [error, setError] = React.useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      http.put<ModelPrice>(`/admin/model-prices/${form.model.trim()}`, {
        provider: form.provider.trim(),
        display_name: form.display_name.trim(),
        context_window: form.context_window ? Math.round(Number(form.context_window)) : null,
        active: form.active,
        ...Object.fromEntries(PRICE_FIELDS.map((f) => [f, String(Number(form.prices[f]) || 0)])),
      }),
    onSuccess: () => {
      toast.success(t("prices.saved"));
      onClose();
      void qc.invalidateQueries({ queryKey: PRICES_KEY });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });
  const valid =
    /^[^/\s]+\/\S+$/.test(form.model.trim()) &&
    form.provider.trim() !== "" &&
    PRICE_FIELDS.every((f) => form.prices[f] !== "" && Number(form.prices[f]) >= 0);
  return (
    <Dialog open={price !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={existing ? t("prices.editTitle", { model: existing.model }) : t("prices.newTitle")} description={t("prices.formDescription")}>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) save.mutate();
          }}
        >
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Field label={t("prices.model")} htmlFor="price-model" hint={t("prices.modelHint")}>
            <Input
              id="price-model"
              required
              disabled={Boolean(existing)}
              value={form.model}
              onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("prices.provider")} htmlFor="price-provider">
              <Input id="price-provider" required value={form.provider} onChange={(e) => setForm((f) => ({ ...f, provider: e.target.value }))} />
            </Field>
            <Field label={t("prices.displayName")} htmlFor="price-name">
              <Input id="price-name" value={form.display_name} onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))} />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {PRICE_FIELDS.map((field) => (
              <Field key={field} label={t(`prices.fields.${field}`)} htmlFor={`price-${field}`}>
                <Input
                  id={`price-${field}`}
                  type="number"
                  min={0}
                  step={0.0001}
                  value={form.prices[field]}
                  onChange={(e) => setForm((f) => ({ ...f, prices: { ...f.prices, [field]: e.target.value } }))}
                />
              </Field>
            ))}
          </div>
          <Field label={t("prices.contextWindow")} htmlFor="price-context">
            <Input
              id="price-context"
              type="number"
              min={1}
              value={form.context_window}
              onChange={(e) => setForm((f) => ({ ...f, context_window: e.target.value }))}
            />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={form.active} onCheckedChange={(active) => setForm((f) => ({ ...f, active }))} aria-label={t("prices.active")} />
            {t("prices.active")}
          </label>
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

export default function AdminModelPricesPage() {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const prices = useQuery({ queryKey: PRICES_KEY, queryFn: () => http.get<ModelPrice[]>("/admin/model-prices") });
  const [editing, setEditing] = React.useState<ModelPrice | null | "new">(null);
  const [deleting, setDeleting] = React.useState<ModelPrice | null>(null);
  const remove = useMutation({
    mutationFn: (model: string) => http.del(`/admin/model-prices/${model}`),
    onSuccess: () => {
      setDeleting(null);
      toast.success(t("prices.deleted"));
      void qc.invalidateQueries({ queryKey: PRICES_KEY });
    },
    onError: (err) => toast.error(errorText(err)),
  });

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={t("prices.title")}
        description={t("prices.description")}
        actions={
          <Button variant="primary" onClick={() => setEditing("new")}>
            <Plus />
            {t("prices.new")}
          </Button>
        }
      />
      <Card>
        {prices.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={6} />
          </div>
        ) : prices.error || !prices.data ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void prices.refetch()} />
          </div>
        ) : prices.data.length === 0 ? (
          <div className="p-4">
            <EmptyState icon={<Cpu />} title={t("prices.emptyTitle")} description={t("prices.empty")} />
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{t("prices.model")}</TH>
                <TH className="text-right">{t("prices.fields.input_per_mtok_usd")}</TH>
                <TH className="text-right">{t("prices.fields.output_per_mtok_usd")}</TH>
                <TH className="hidden text-right md:table-cell">{t("prices.fields.cache_read_per_mtok_usd")}</TH>
                <TH className="hidden text-right md:table-cell">{t("prices.fields.cache_write_per_mtok_usd")}</TH>
                <TH className="hidden text-right lg:table-cell">{t("prices.contextWindow")}</TH>
                <TH className="hidden lg:table-cell">{tc("updated")}</TH>
                <TH className="w-32" />
              </tr>
            </THead>
            <TBody>
              {prices.data.map((p) => (
                <TR key={p.model}>
                  <TD>
                    <span className="font-medium">{p.display_name || p.model}</span>
                    {!p.active ? <Badge tone="outline" className="ml-2">{t("prices.inactive")}</Badge> : null}
                    <span className="block font-mono text-xs text-fg-subtle">{p.model}</span>
                  </TD>
                  <TD className="tabular text-right">{formatUsd(p.input_per_mtok_usd, locale)}</TD>
                  <TD className="tabular text-right">{formatUsd(p.output_per_mtok_usd, locale)}</TD>
                  <TD className="tabular hidden text-right md:table-cell">{formatUsd(p.cache_read_per_mtok_usd, locale)}</TD>
                  <TD className="tabular hidden text-right md:table-cell">{formatUsd(p.cache_write_per_mtok_usd, locale)}</TD>
                  <TD className="tabular hidden text-right lg:table-cell">
                    {p.context_window ? formatNumber(p.context_window, locale) : "—"}
                  </TD>
                  <TD className="hidden text-fg-muted lg:table-cell">{formatDate(p.updated_at, locale)}</TD>
                  <TD className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="sm" onClick={() => setEditing(p)}>
                        {tc("edit")}
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setDeleting(p)}>
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
      <p className="text-xs text-fg-subtle">{t("prices.footnote")}</p>
      {editing !== null ? <PriceDialog key={editing === "new" ? "new" : editing.model} price={editing} onClose={() => setEditing(null)} /> : null}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("prices.deleteTitle", { model: deleting?.model ?? "" })}
        description={t("prices.deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.model);
        }}
      />
    </div>
  );
}

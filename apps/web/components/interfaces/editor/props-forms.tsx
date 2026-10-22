"use client";

import { Button, Checkbox, Input, Select } from "@messer/ui";
import { ChevronDown, ChevronUp, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";

import type { ColumnDef, ComponentDef, FilterDef, FormFieldDef, Option, RowAction, ValueFormat } from "../types";
import { type BindingContext, BindingEditor } from "./binding-editor";
import { AreaField, Group, ListField, NumberField, SelectField, SwitchField, TextField } from "./fields";

type Props = Record<string, unknown>;

const str = (v: unknown) => (typeof v === "string" ? v : "");
const num = (v: unknown, fallback: number | null = null) => (typeof v === "number" ? v : fallback);
const list = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
const opt = (v: string) => (v.trim() === "" ? null : v);

const FORMATS: ValueFormat[] = ["text", "number", "currency", "percent", "date", "datetime", "boolean", "badge"];

/** Type-specific properties of a component. */
export function PropsForm({ comp, onChange, ctx }: { comp: ComponentDef; onChange: (props: Props) => void; ctx: BindingContext }) {
  const t = useTranslations("interfaces.props");
  const p = comp.props;
  const set = (patch: Props) => onChange({ ...p, ...patch });
  switch (comp.type) {
    case "data_table":
      return (
        <>
          <Group title={t("columns")}>
            <ColumnsEditor columns={list<ColumnDef>(p.columns)} onChange={(columns) => set({ columns })} />
          </Group>
          <Group title={t("behaviour")}>
            <NumberField label={t("pageSize")} value={num(p.page_size, 10)} min={5} max={100} onChange={(v) => set({ page_size: v ?? 10 })} />
            <SwitchField label={t("searchable")} checked={p.searchable === true} onChange={(v) => set({ searchable: v })} />
            <TextField label={t("emptyText")} value={str(p.empty_text)} onChange={(v) => set({ empty_text: opt(v) })} />
          </Group>
          <Group title={t("filters")}>
            <FiltersEditor filters={list<FilterDef>(p.filters)} onChange={(filters) => set({ filters })} />
          </Group>
          <Group title={t("rowAction")}>
            <RowActionEditor value={(p.row_action as RowAction | null) ?? null} onChange={(row_action) => set({ row_action })} ctx={ctx} />
          </Group>
        </>
      );
    case "record_list":
      return (
        <>
          <Group title={t("fields")}>
            <TextField label={t("titleField")} value={str(p.title_field)} onChange={(v) => set({ title_field: opt(v) })} mono />
            <TextField label={t("subtitleField")} value={str(p.subtitle_field)} onChange={(v) => set({ subtitle_field: opt(v) })} mono />
            <ListField label={t("metaFields")} value={list<string>(p.meta_fields)} onChange={(meta_fields) => set({ meta_fields })} />
            <TextField label={t("badgeField")} value={str(p.badge_field)} onChange={(v) => set({ badge_field: opt(v) })} mono />
          </Group>
          <Group title={t("behaviour")}>
            <NumberField label={t("pageSize")} value={num(p.page_size, 10)} min={5} max={100} onChange={(v) => set({ page_size: v ?? 10 })} />
            <SwitchField label={t("searchable")} checked={p.searchable === true} onChange={(v) => set({ searchable: v })} />
            <TextField label={t("emptyText")} value={str(p.empty_text)} onChange={(v) => set({ empty_text: opt(v) })} />
          </Group>
          <Group title={t("filters")}>
            <FiltersEditor filters={list<FilterDef>(p.filters)} onChange={(filters) => set({ filters })} />
          </Group>
          <Group title={t("rowAction")}>
            <RowActionEditor value={(p.row_action as RowAction | null) ?? null} onChange={(row_action) => set({ row_action })} ctx={ctx} />
          </Group>
        </>
      );
    case "chart":
      return (
        <>
          <Group title={t("chart")}>
            <SelectField
              label={t("chartKind")}
              value={str(p.chart) || "bar"}
              options={(["bar", "line", "area", "pie"] as const).map((k) => ({ value: k, label: t(`chartKinds.${k}`) }))}
              onChange={(chart) => set({ chart })}
            />
            <TextField label={t("xAxis")} hint={t("xAxisHint")} value={str(p.x)} onChange={(v) => set({ x: opt(v) })} mono />
            <ListField label={t("series")} hint={t("seriesHint")} value={list<string>(p.y)} onChange={(y) => set({ y })} />
            <SwitchField label={t("stacked")} checked={p.stacked === true} onChange={(v) => set({ stacked: v })} />
            <SwitchField label={t("legend")} checked={p.legend !== false} onChange={(v) => set({ legend: v })} />
            <ValueFormatFields p={p} set={set} formats={["number", "currency", "percent"]} />
          </Group>
          <Group title={t("filters")}>
            <FiltersEditor filters={list<FilterDef>(p.filters)} onChange={(filters) => set({ filters })} />
          </Group>
        </>
      );
    case "kpi":
      return (
        <Group title={t("kpi")}>
          <TextField label={t("valueColumn")} hint={t("valueColumnHint")} value={str(p.value)} onChange={(v) => set({ value: opt(v) })} mono />
          <ValueFormatFields p={p} set={set} formats={["number", "currency", "percent", "text"]} />
          <NumberField label={t("decimals")} value={num(p.decimals)} min={0} max={4} nullable onChange={(decimals) => set({ decimals })} />
          <TextField label={t("deltaColumn")} value={str(p.delta)} onChange={(v) => set({ delta: opt(v) })} mono />
          <SelectField
            label={t("deltaFormat")}
            value={str(p.delta_format) || "percent"}
            options={[
              { value: "percent", label: t("formats.percent") },
              { value: "number", label: t("formats.number") },
            ]}
            onChange={(delta_format) => set({ delta_format })}
          />
          <SelectField
            label={t("trend")}
            value={str(p.trend) || "up_is_good"}
            options={[
              { value: "up_is_good", label: t("upIsGood") },
              { value: "down_is_good", label: t("downIsGood") },
            ]}
            onChange={(trend) => set({ trend })}
          />
          <TextField label={t("hint")} value={str(p.hint)} onChange={(v) => set({ hint: opt(v) })} />
        </Group>
      );
    case "form":
      return (
        <>
          <Group title={t("formFields")}>
            <FormFieldsEditor fields={list<FormFieldDef>(p.fields)} onChange={(fields) => set({ fields })} />
          </Group>
          <Group title={t("behaviour")}>
            <TextField label={t("submitLabel")} value={str(p.submit_label)} onChange={(v) => set({ submit_label: opt(v) })} />
            <TextField label={t("successMessage")} value={str(p.success_message)} onChange={(v) => set({ success_message: opt(v) })} />
            <SwitchField label={t("resetOnSubmit")} checked={p.reset_on_submit !== false} onChange={(v) => set({ reset_on_submit: v })} />
          </Group>
        </>
      );
    case "chat":
      return (
        <Group title={t("chat")}>
          <AreaField label={t("greeting")} value={str(p.greeting)} onChange={(v) => set({ greeting: opt(v) })} />
          <TextField label={t("placeholder")} value={str(p.placeholder)} onChange={(v) => set({ placeholder: opt(v) })} />
          <ListField label={t("suggestions")} separator={"\n"} hint={t("suggestionsHint")} value={list<string>(p.suggestions)} onChange={(suggestions) => set({ suggestions: suggestions.slice(0, 6) })} />
        </Group>
      );
    case "calendar":
      return (
        <Group title={t("calendar")}>
          <TextField label={t("dateField")} value={str(p.date_field)} onChange={(v) => set({ date_field: v })} mono />
          <TextField label={t("endField")} value={str(p.end_field)} onChange={(v) => set({ end_field: opt(v) })} mono />
          <TextField label={t("titleField")} value={str(p.title_field)} onChange={(v) => set({ title_field: opt(v) })} mono />
          <SelectField
            label={t("view")}
            value={str(p.view) || "month"}
            options={[
              { value: "month", label: t("viewMonth") },
              { value: "agenda", label: t("viewAgenda") },
            ]}
            onChange={(view) => set({ view })}
          />
        </Group>
      );
    case "file_upload":
      return (
        <Group title={t("upload")}>
          {ctx.kbs.length === 0 ? (
            <p className="text-xs text-fg-muted">{t("noKnowledgeBases")}</p>
          ) : (
            <SelectField
              label={t("targetKb")}
              value={str(p.kb_id) || undefined}
              placeholder={t("chooseKb")}
              options={ctx.kbs.map((k) => ({ value: k.id, label: k.name }))}
              onChange={(kb_id) => set({ kb_id })}
            />
          )}
          <ListField label={t("accept")} hint={t("acceptHint")} value={list<string>(p.accept)} onChange={(accept) => set({ accept: accept.map((a) => (a.startsWith(".") ? a : `.${a}`).toLowerCase()) })} />
          <NumberField label={t("maxMb")} value={num(p.max_mb, 20)} min={1} max={100} onChange={(v) => set({ max_mb: v ?? 20 })} />
          <SwitchField label={t("multiple")} checked={p.multiple !== false} onChange={(v) => set({ multiple: v })} />
          <TextField label={t("label")} value={str(p.label)} onChange={(v) => set({ label: opt(v) })} />
          <TextField label={t("help")} value={str(p.help)} onChange={(v) => set({ help: opt(v) })} />
        </Group>
      );
    case "action_button":
      return (
        <Group title={t("button")}>
          <TextField label={t("label")} value={str(p.label)} onChange={(label) => set({ label })} />
          <SelectField
            label={t("variant")}
            value={str(p.variant) || "primary"}
            options={(["primary", "secondary", "danger"] as const).map((v) => ({ value: v, label: t(`variants.${v}`) }))}
            onChange={(variant) => set({ variant })}
          />
          <TextField label={t("description")} value={str(p.description)} onChange={(v) => set({ description: opt(v) })} />
          <TextField label={t("confirm")} hint={t("confirmHint")} value={str(p.confirm)} onChange={(v) => set({ confirm: opt(v) })} />
          <TextField label={t("successMessage")} value={str(p.success_message)} onChange={(v) => set({ success_message: opt(v) })} />
        </Group>
      );
    case "approvals_inbox":
      return (
        <Group title={t("behaviour")}>
          <NumberField label={t("pageSize")} value={num(p.page_size, 10)} min={5} max={100} onChange={(v) => set({ page_size: v ?? 10 })} />
        </Group>
      );
    default:
      return null;
  }
}

function ValueFormatFields({ p, set, formats }: { p: Props; set: (patch: Props) => void; formats: string[] }) {
  const t = useTranslations("interfaces.props");
  return (
    <>
      <SelectField label={t("format")} value={str(p.format) || "number"} options={formats.map((f) => ({ value: f, label: t(`formats.${f}`) }))} onChange={(format) => set({ format })} />
      {p.format === "currency" ? (
        <TextField label={t("currency")} value={str(p.currency) || "EUR"} onChange={(v) => set({ currency: v.toUpperCase().slice(0, 3) })} mono />
      ) : null}
    </>
  );
}

function move<T>(items: T[], i: number, delta: number): T[] {
  const j = i + delta;
  if (j < 0 || j >= items.length) return items;
  const next = [...items];
  [next[i], next[j]] = [next[j] as T, next[i] as T];
  return next;
}

function RowControls({ i, count, onMove, onRemove, label }: { i: number; count: number; onMove: (d: number) => void; onRemove: () => void; label: string }) {
  const t = useTranslations("interfaces.props");
  return (
    <div className="flex shrink-0 items-center">
      <Button size="icon-sm" variant="ghost" aria-label={t("moveUp", { item: label })} disabled={i === 0} onClick={() => onMove(-1)}>
        <ChevronUp />
      </Button>
      <Button size="icon-sm" variant="ghost" aria-label={t("moveDown", { item: label })} disabled={i === count - 1} onClick={() => onMove(1)}>
        <ChevronDown />
      </Button>
      <Button size="icon-sm" variant="ghost" aria-label={t("remove", { item: label })} onClick={onRemove}>
        <X />
      </Button>
    </div>
  );
}

function ColumnsEditor({ columns, onChange }: { columns: ColumnDef[]; onChange: (c: ColumnDef[]) => void }) {
  const t = useTranslations("interfaces.props");
  const set = (i: number, patch: Partial<ColumnDef>) => onChange(columns.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <div className="flex flex-col gap-2">
      {columns.length === 0 ? <p className="text-xs text-fg-subtle">{t("columnsHint")}</p> : null}
      {columns.map((c, i) => (
        <div key={i} className="flex flex-col gap-1 rounded-md border border-border p-2">
          <div className="flex items-center gap-1.5">
            <Input aria-label={t("columnKey")} placeholder={t("columnKey")} value={c.key} onChange={(e) => set(i, { key: e.target.value })} className="font-mono text-xs" />
            <RowControls i={i} count={columns.length} label={c.key} onMove={(d) => onChange(move(columns, i, d))} onRemove={() => onChange(columns.filter((_, j) => j !== i))} />
          </div>
          <div className="flex gap-1.5">
            <Input aria-label={t("columnLabel")} placeholder={t("columnLabel")} value={c.label ?? ""} onChange={(e) => set(i, { label: opt(e.target.value) })} />
            <div className="w-32 shrink-0">
              <Select aria-label={t("format")} value={c.format ?? "text"} onValueChange={(f) => set(i, { format: f as ValueFormat })} options={FORMATS.map((f) => ({ value: f, label: t(`formats.${f}`) }))} />
            </div>
          </div>
        </div>
      ))}
      <Button size="sm" variant="secondary" onClick={() => onChange([...columns, { key: "", format: "text" }])}>
        <Plus />
        {t("addColumn")}
      </Button>
    </div>
  );
}

function OptionsField({ options, onChange }: { options: Option[]; onChange: (o: Option[]) => void }) {
  const t = useTranslations("interfaces.props");
  return (
    <ListField
      label={t("options")}
      separator={"\n"}
      hint={t("optionsHint")}
      value={options.map((o) => (o.label && o.label !== o.value ? `${o.value}=${o.label}` : o.value))}
      onChange={(lines) =>
        onChange(
          lines.map((line) => {
            const [value, ...rest] = line.split("=");
            const v = (value ?? "").trim();
            return { value: v, label: rest.join("=").trim() || v };
          }),
        )
      }
    />
  );
}

function FiltersEditor({ filters, onChange }: { filters: FilterDef[]; onChange: (f: FilterDef[]) => void }) {
  const t = useTranslations("interfaces.props");
  const set = (i: number, patch: Partial<FilterDef>) => onChange(filters.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-fg-subtle">{t("filtersHint")}</p>
      {filters.map((f, i) => (
        <div key={i} className="flex flex-col gap-2 rounded-md border border-border p-2">
          <div className="flex items-center gap-1.5">
            <Input aria-label={t("filterName")} placeholder={t("filterName")} value={f.name} onChange={(e) => set(i, { name: e.target.value })} className="font-mono text-xs" />
            <RowControls i={i} count={filters.length} label={f.name} onMove={(d) => onChange(move(filters, i, d))} onRemove={() => onChange(filters.filter((_, j) => j !== i))} />
          </div>
          <Input aria-label={t("filterLabel")} placeholder={t("filterLabel")} value={f.label} onChange={(e) => set(i, { label: e.target.value })} />
          <Select
            aria-label={t("filterType")}
            value={f.type ?? "text"}
            onValueChange={(type) => set(i, { type: type as FilterDef["type"] })}
            options={(["text", "select", "date", "number"] as const).map((k) => ({ value: k, label: t(`filterTypes.${k}`) }))}
          />
          {f.type === "select" ? <OptionsField options={f.options ?? []} onChange={(options) => set(i, { options })} /> : null}
          <Input
            aria-label={t("default")}
            placeholder={t("default")}
            value={f.default === null || f.default === undefined ? "" : String(f.default)}
            onChange={(e) => set(i, { default: e.target.value === "" ? null : e.target.value })}
          />
        </div>
      ))}
      <Button size="sm" variant="secondary" onClick={() => onChange([...filters, { name: `filtro_${filters.length + 1}`, label: t("newFilter"), type: "text" }])}>
        <Plus />
        {t("addFilter")}
      </Button>
    </div>
  );
}

function FormFieldsEditor({ fields, onChange }: { fields: FormFieldDef[]; onChange: (f: FormFieldDef[]) => void }) {
  const t = useTranslations("interfaces.props");
  const set = (i: number, patch: Partial<FormFieldDef>) => onChange(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  return (
    <div className="flex flex-col gap-2">
      {fields.map((f, i) => (
        <div key={i} className="flex flex-col gap-2 rounded-md border border-border p-2">
          <div className="flex items-center gap-1.5">
            <Input aria-label={t("fieldName")} placeholder={t("fieldName")} value={f.name} onChange={(e) => set(i, { name: e.target.value })} className="font-mono text-xs" />
            <RowControls i={i} count={fields.length} label={f.name} onMove={(d) => onChange(move(fields, i, d))} onRemove={() => onChange(fields.filter((_, j) => j !== i))} />
          </div>
          <Input aria-label={t("fieldLabel")} placeholder={t("fieldLabel")} value={f.label} onChange={(e) => set(i, { label: e.target.value })} />
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <Select
                aria-label={t("fieldType")}
                value={f.type ?? "text"}
                onValueChange={(type) => set(i, { type: type as FormFieldDef["type"] })}
                options={(["text", "textarea", "number", "email", "date", "select", "checkbox"] as const).map((k) => ({ value: k, label: t(`fieldTypes.${k}`) }))}
              />
            </div>
            <label className="flex items-center gap-1.5 text-xs text-fg">
              <Checkbox checked={f.required === true} onCheckedChange={(c) => set(i, { required: c === true })} />
              {t("required")}
            </label>
          </div>
          {f.type === "select" ? <OptionsField options={f.options ?? []} onChange={(options) => set(i, { options })} /> : null}
          {f.type === "number" ? (
            <div className="grid grid-cols-2 gap-2">
              <NumberField label={t("min")} value={f.min ?? null} nullable onChange={(min) => set(i, { min })} />
              <NumberField label={t("max")} value={f.max ?? null} nullable onChange={(max) => set(i, { max })} />
            </div>
          ) : null}
          <Input aria-label={t("placeholder")} placeholder={t("placeholder")} value={f.placeholder ?? ""} onChange={(e) => set(i, { placeholder: opt(e.target.value) })} />
          <Input aria-label={t("help")} placeholder={t("help")} value={f.help ?? ""} onChange={(e) => set(i, { help: opt(e.target.value) })} />
        </div>
      ))}
      <Button
        size="sm"
        variant="secondary"
        onClick={() => onChange([...fields, { name: `campo_${fields.length + 1}`, label: t("newField"), type: "text", required: false }])}
      >
        <Plus />
        {t("addField")}
      </Button>
    </div>
  );
}

function RowActionEditor({ value, onChange, ctx }: { value: RowAction | null; onChange: (v: RowAction | null) => void; ctx: BindingContext }) {
  const t = useTranslations("interfaces.props");
  if (!value) {
    return (
      <Button
        size="sm"
        variant="secondary"
        onClick={() =>
          onChange({
            label: t("rowActionDefault"),
            binding: ctx.workflows.length > 0
              ? { kind: "workflow", workforce: ctx.workflows[0] ?? "", input_mapping: {} }
              : { kind: "agent", workforce: ctx.agents[0] ?? "", prompt: null },
          })
        }
      >
        <Plus />
        {t("addRowAction")}
      </Button>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <TextField label={t("label")} value={value.label} onChange={(label) => onChange({ ...value, label })} />
      <TextField label={t("confirm")} hint={t("confirmHint")} value={value.confirm ?? ""} onChange={(v) => onChange({ ...value, confirm: opt(v) })} />
      <BindingEditor
        type="action_button"
        allowed={["workflow", "agent"]}
        binding={value.binding && "workforce" in value.binding ? value.binding : null}
        onChange={(binding) => onChange({ ...value, binding: binding && (binding.kind === "agent" || binding.kind === "workflow") ? binding : null })}
        ctx={ctx}
      />
      <p className="text-xs text-fg-subtle">{t("rowActionHint")}</p>
      <Button size="sm" variant="danger" onClick={() => onChange(null)}>
        {t("removeRowAction")}
      </Button>
    </div>
  );
}


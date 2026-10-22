"use client";

import { Button, Checkbox, Field, Input, Select } from "@messer/ui";
import { Plus, Wand2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { CodeEditor } from "@/components/studio/monaco";

import { type KbOption, useKbTables } from "../api";
import {
  type AgentBinding,
  type Binding,
  type BindingKind,
  CONTEXT_KEYS,
  type ComponentType,
  type KnowledgeSearchBinding,
  type KnowledgeSqlBinding,
  type Scalar,
  type SqlParam,
  type StaticBinding,
  type WorkflowBinding,
} from "../types";
import { AreaField, NumberField, SelectField, TextField } from "./fields";
import { ALLOWED_BINDINGS, BINDING_OPTIONAL, emptyBinding } from "./model";

export interface BindingContext {
  agents: string[];
  workflows: string[];
  kbs: KbOption[];
  /** Field names of the form being edited (to map them to workflow inputs). */
  formFields?: string[];
}

function quoteIdent(name: string): string {
  return `"${name.replace(/"/g, '""')}"`;
}

/** Editor of a component's binding: kind and its parameters, with pickers for KBs, tables, agents and workflows. */
export function BindingEditor({
  type,
  binding,
  onChange,
  ctx,
  allowed,
}: {
  type: ComponentType;
  binding: Binding | null | undefined;
  onChange: (binding: Binding | null) => void;
  ctx: BindingContext;
  /** Override the kinds allowed (row actions: agent | workflow). */
  allowed?: BindingKind[];
}) {
  const t = useTranslations("interfaces.binding");
  const kinds = allowed ?? ALLOWED_BINDINGS[type];
  const optional = !allowed && BINDING_OPTIONAL[type];
  const kbIds = ctx.kbs.map((k) => k.id);
  const current = binding?.kind ?? (optional ? "none" : kinds[0]);
  const options = [
    ...(optional ? [{ value: "none", label: t("none") }] : []),
    ...kinds.map((k) => ({ value: k, label: t(`kinds.${k}`) })),
  ];
  return (
    <div className="flex flex-col gap-3">
      {options.length > 1 ? (
        <SelectField
          label={t("kind")}
          value={current}
          options={options}
          onChange={(k) => onChange(k === "none" ? null : emptyBinding(k as BindingKind, { ...ctx, kbIds }))}
        />
      ) : null}
      {binding?.kind === "knowledge_sql" ? <SqlEditor binding={binding} onChange={onChange} ctx={ctx} /> : null}
      {binding?.kind === "knowledge_search" ? <SearchEditor binding={binding} onChange={onChange} ctx={ctx} /> : null}
      {binding?.kind === "agent" ? <AgentEditor binding={binding} onChange={onChange} ctx={ctx} type={type} /> : null}
      {binding?.kind === "workflow" ? <WorkflowEditor binding={binding} onChange={onChange} ctx={ctx} type={type} /> : null}
      {binding?.kind === "approvals" ? (
        <SelectField
          label={t("approvalsStatus")}
          value={binding.status ?? "pending"}
          options={[
            { value: "pending", label: t("approvalsPending") },
            { value: "all", label: t("approvalsAll") },
          ]}
          onChange={(status) => onChange({ ...binding, status })}
        />
      ) : null}
      {binding?.kind === "static" ? <StaticEditor binding={binding} onChange={onChange} /> : null}
    </div>
  );
}

function KbSelect({ value, onChange, kbs, label }: { value: string; onChange: (id: string) => void; kbs: KbOption[]; label: string }) {
  const t = useTranslations("interfaces.binding");
  if (kbs.length === 0) return <p className="text-xs text-fg-muted">{t("noKnowledgeBases")}</p>;
  return <SelectField label={label} value={value || undefined} placeholder={t("chooseKb")} options={kbs.map((k) => ({ value: k.id, label: k.name }))} onChange={onChange} />;
}

function SqlEditor({ binding, onChange, ctx }: { binding: KnowledgeSqlBinding; onChange: (b: Binding) => void; ctx: BindingContext }) {
  const t = useTranslations("interfaces.binding");
  const tables = useKbTables(binding.kb_id || null);
  const [table, setTable] = React.useState("");
  const set = (patch: Partial<KnowledgeSqlBinding>) => onChange({ ...binding, ...patch });
  const generate = () => {
    const meta = tables.data?.find((x) => x.name === table);
    if (!meta) return;
    const cols = meta.columns.map((c) => c.name).filter((c) => !c.startsWith("_"));
    set({ sql: `SELECT ${cols.length > 0 ? cols.map(quoteIdent).join(", ") : "*"} FROM ${quoteIdent(meta.name)} LIMIT 100`, params: [] });
  };
  return (
    <>
      <KbSelect label={t("knowledgeBase")} value={binding.kb_id} kbs={ctx.kbs} onChange={(kb_id) => set({ kb_id })} />
      {binding.kb_id ? (
        <div className="flex items-end gap-2">
          <div className="min-w-0 flex-1">
            <SelectField
              label={t("table")}
              value={table || undefined}
              placeholder={tables.isPending ? t("loadingTables") : t("chooseTable")}
              options={(tables.data ?? []).map((x) => ({ value: x.name, label: `${x.name} (${x.row_count})` }))}
              onChange={setTable}
            />
          </div>
          <Button size="sm" variant="secondary" disabled={!table} onClick={generate} title={t("generateHint")}>
            <Wand2 />
            {t("generate")}
          </Button>
        </div>
      ) : null}
      <Field label={t("sql")} hint={t("sqlHint")}>
        <div className="h-40 overflow-hidden rounded-md border border-border">
          <CodeEditor value={binding.sql} onChange={(sql) => set({ sql })} language="sql" ariaLabel={t("sql")} />
        </div>
      </Field>
      <ParamsEditor params={binding.params} onChange={(params) => set({ params })} />
      <NumberField label={t("limit")} value={binding.limit ?? 500} min={1} max={5000} onChange={(v) => set({ limit: v ?? 500 })} />
    </>
  );
}

type ParamKind = "value" | "input" | "context";

function paramKind(p: SqlParam): ParamKind {
  if (p !== null && typeof p === "object") return "input" in p ? "input" : "context";
  return "value";
}

function ParamsEditor({ params, onChange }: { params: SqlParam[]; onChange: (params: SqlParam[]) => void }) {
  const t = useTranslations("interfaces.binding");
  const set = (i: number, p: SqlParam) => onChange(params.map((x, j) => (j === i ? p : x)));
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-fg">{t("params")}</span>
        <Button size="sm" variant="ghost" onClick={() => onChange([...params, ""])}>
          <Plus />
          {t("addParam")}
        </Button>
      </div>
      {params.length === 0 ? <p className="text-xs text-fg-subtle">{t("paramsHint")}</p> : null}
      {params.map((p, i) => {
        const kind = paramKind(p);
        return (
          <div key={i} className="flex items-center gap-1.5">
            <span className="w-7 shrink-0 font-mono text-xs text-fg-muted">${i + 1}</span>
            <div className="w-28 shrink-0">
              <Select
                aria-label={t("paramKind", { n: i + 1 })}
                value={kind}
                onValueChange={(k) =>
                  set(i, k === "input" ? { input: "filtro", default: null } : k === "context" ? { context: "today" } : "")
                }
                options={[
                  { value: "value", label: t("paramValue") },
                  { value: "input", label: t("paramInput") },
                  { value: "context", label: t("paramContext") },
                ]}
              />
            </div>
            {kind === "value" ? (
              <Input aria-label={t("paramValue")} value={p === null ? "" : String(p)} onChange={(e) => set(i, e.target.value)} />
            ) : kind === "input" && p !== null && typeof p === "object" && "input" in p ? (
              <>
                <Input aria-label={t("paramInputName")} value={p.input} onChange={(e) => set(i, { ...p, input: e.target.value })} className="font-mono text-xs" />
                <Input
                  aria-label={t("paramDefault")}
                  placeholder={t("paramDefault")}
                  value={p.default === null || p.default === undefined ? "" : String(p.default)}
                  onChange={(e) => set(i, { ...p, default: e.target.value === "" ? null : e.target.value })}
                />
              </>
            ) : p !== null && typeof p === "object" && "context" in p ? (
              <Select
                aria-label={t("paramContext")}
                value={p.context}
                onValueChange={(context) => set(i, { context })}
                options={CONTEXT_KEYS.map((k) => ({ value: k, label: t(`context.${k}`) }))}
              />
            ) : null}
            <Button size="icon-sm" variant="ghost" aria-label={t("removeParam", { n: i + 1 })} onClick={() => onChange(params.filter((_, j) => j !== i))}>
              <X />
            </Button>
          </div>
        );
      })}
    </div>
  );
}

function SearchEditor({ binding, onChange, ctx }: { binding: KnowledgeSearchBinding; onChange: (b: Binding) => void; ctx: BindingContext }) {
  const t = useTranslations("interfaces.binding");
  const set = (patch: Partial<KnowledgeSearchBinding>) => onChange({ ...binding, ...patch });
  return (
    <>
      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1 text-sm font-medium text-fg">{t("knowledgeBases")}</legend>
        {ctx.kbs.length === 0 ? <p className="text-xs text-fg-muted">{t("noKnowledgeBases")}</p> : null}
        {ctx.kbs.map((kb) => {
          const checked = binding.kb_ids.includes(kb.id);
          return (
            <label key={kb.id} className="flex items-center gap-2 text-sm text-fg">
              <Checkbox
                checked={checked}
                onCheckedChange={(c) =>
                  set({ kb_ids: c === true ? [...binding.kb_ids, kb.id].slice(0, 5) : binding.kb_ids.filter((id) => id !== kb.id) })
                }
              />
              {kb.name}
            </label>
          );
        })}
      </fieldset>
      <TextField label={t("defaultQuery")} value={binding.query ?? ""} onChange={(query) => set({ query })} />
      <TextField
        label={t("queryInput")}
        hint={t("queryInputHint")}
        value={binding.query_input ?? ""}
        onChange={(v) => set({ query_input: v.trim() === "" ? null : v.trim() })}
        mono
      />
      <SelectField
        label={t("mode")}
        value={binding.mode ?? "hybrid"}
        options={(["hybrid", "vector", "keyword"] as const).map((m) => ({ value: m, label: t(`modes.${m}`) }))}
        onChange={(mode) => set({ mode })}
      />
      <NumberField label={t("results")} value={binding.k ?? 8} min={1} max={50} onChange={(k) => set({ k: k ?? 8 })} />
    </>
  );
}

function AgentEditor({ binding, onChange, ctx, type }: { binding: AgentBinding; onChange: (b: Binding) => void; ctx: BindingContext; type: ComponentType }) {
  const t = useTranslations("interfaces.binding");
  return (
    <>
      {ctx.agents.length === 0 ? (
        <p className="text-xs text-fg-muted">{t("noAgents")}</p>
      ) : (
        <SelectField
          label={t("agent")}
          value={binding.workforce || undefined}
          placeholder={t("chooseAgent")}
          options={ctx.agents.map((a) => ({ value: a, label: a }))}
          onChange={(workforce) => onChange({ ...binding, workforce })}
        />
      )}
      {type !== "chat" ? (
        <AreaField
          label={t("prompt")}
          hint={t("promptHint")}
          value={binding.prompt ?? ""}
          onChange={(prompt) => onChange({ ...binding, prompt: prompt.trim() === "" ? null : prompt })}
        />
      ) : null}
    </>
  );
}

function WorkflowEditor({ binding, onChange, ctx, type }: { binding: WorkflowBinding; onChange: (b: Binding) => void; ctx: BindingContext; type: ComponentType }) {
  const t = useTranslations("interfaces.binding");
  const entries = Object.entries(binding.input_mapping);
  const setEntries = (list: [string, Scalar][]) => onChange({ ...binding, input_mapping: Object.fromEntries(list) });
  return (
    <>
      {ctx.workflows.length === 0 ? (
        <p className="text-xs text-fg-muted">{t("noWorkflows")}</p>
      ) : (
        <SelectField
          label={t("workflow")}
          value={binding.workforce || undefined}
          placeholder={t("chooseWorkflow")}
          options={ctx.workflows.map((w) => ({ value: w, label: w }))}
          onChange={(workforce) => onChange({ ...binding, workforce })}
        />
      )}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium text-fg">{t("inputMapping")}</span>
          <div className="flex gap-1">
            {type === "form" && ctx.formFields && ctx.formFields.length > 0 ? (
              <Button size="sm" variant="ghost" onClick={() => setEntries(ctx.formFields!.map((f) => [f, `$form.${f}`]))}>
                <Wand2 />
                {t("mapForm")}
              </Button>
            ) : null}
            <Button size="sm" variant="ghost" onClick={() => setEntries([...entries, [`param_${entries.length + 1}`, ""]])}>
              <Plus />
              {t("addMapping")}
            </Button>
          </div>
        </div>
        <p className="text-xs text-fg-subtle">{t("mappingHint")}</p>
        {entries.map(([key, value], i) => (
          <div key={i} className="flex items-center gap-1.5">
            <Input
              aria-label={t("mappingKey", { n: i + 1 })}
              value={key}
              onChange={(e) => setEntries(entries.map((x, j) => (j === i ? [e.target.value, x[1]] : x)))}
              className="font-mono text-xs"
            />
            <Input
              aria-label={t("mappingValue", { n: i + 1 })}
              value={value === null ? "" : String(value)}
              onChange={(e) => setEntries(entries.map((x, j) => (j === i ? [x[0], e.target.value] : x)))}
              className="font-mono text-xs"
            />
            <Button size="icon-sm" variant="ghost" aria-label={t("removeMapping", { n: i + 1 })} onClick={() => setEntries(entries.filter((_, j) => j !== i))}>
              <X />
            </Button>
          </div>
        ))}
      </div>
    </>
  );
}

function StaticEditor({ binding, onChange }: { binding: StaticBinding; onChange: (b: Binding) => void }) {
  const t = useTranslations("interfaces.binding");
  const [text, setText] = React.useState(() => JSON.stringify(binding.data, null, 2));
  const [error, setError] = React.useState<string | null>(null);
  return (
    <AreaField
      label={t("staticData")}
      hint={t("staticHint")}
      value={text}
      error={error}
      mono
      rows={8}
      onChange={(raw) => {
        setText(raw);
        try {
          const data = JSON.parse(raw) as unknown;
          if (data === null || typeof data !== "object") throw new Error("shape");
          setError(null);
          onChange({ ...binding, data: data as StaticBinding["data"] });
        } catch {
          setError(t("invalidJson"));
        }
      }}
    />
  );
}

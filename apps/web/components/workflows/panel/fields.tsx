"use client";

import {
  Button,
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  Textarea,
  cn,
} from "@messer/ui";
import { Braces, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import type { BindingGroup, BindingOption } from "@/lib/workflows/bindings";

export function FieldIssues({ messages }: { messages: string[] }) {
  if (!messages.length) return null;
  return (
    <ul className="mt-1 space-y-0.5" role="alert">
      {messages.map((m) => (
        <li key={m} className="text-xs text-danger">
          {m}
        </li>
      ))}
    </ul>
  );
}

/** Section of the node panel: a label, an optional hint and the control. */
export function PanelField({
  label,
  htmlFor,
  hint,
  issues = [],
  children,
  action,
}: {
  label: React.ReactNode;
  htmlFor?: string;
  hint?: React.ReactNode;
  issues?: string[];
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={htmlFor} className="text-xs font-medium text-fg">
          {label}
        </label>
        {action}
      </div>
      {children}
      {hint ? <p className="text-[11px] leading-4 text-fg-subtle">{hint}</p> : null}
      <FieldIssues messages={issues} />
    </div>
  );
}

const GROUP_ORDER: BindingGroup[] = ["loop", "inputs", "nodes", "event"];

/** Popover listing every value the node can bind to; picking one inserts `{{path}}`. */
export function BindingPicker({
  options,
  onPick,
  disabled,
}: {
  options: BindingOption[];
  onPick: (path: string) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("workflows.bindings");
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const q = query.trim().toLowerCase();
  const visible = options.filter((o) => !q || o.path.toLowerCase().includes(q));
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-6 gap-1 px-1.5 text-[11px]" disabled={disabled} aria-label={t("button")}>
          <Braces className="!size-3.5" />
          {t("button")}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="end">
        <div className="border-b border-border p-2">
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("search")} className="h-7" autoFocus />
        </div>
        <div className="max-h-72 overflow-y-auto p-1">
          {visible.length === 0 ? <p className="px-2 py-3 text-xs text-fg-subtle">{t("empty")}</p> : null}
          {GROUP_ORDER.map((group) => {
            const items = visible.filter((o) => o.group === group);
            if (!items.length) return null;
            return (
              <div key={group} className="py-1">
                <p className="px-2 pb-0.5 text-[10px] font-semibold uppercase tracking-wide text-fg-subtle">{t(`groups.${group}`)}</p>
                {items.map((o) => (
                  <button
                    key={o.path}
                    type="button"
                    className="flex w-full items-center justify-between gap-2 rounded-sm px-2 py-1 text-left hover:bg-subtle focus-visible:bg-subtle focus-visible:outline-none"
                    onClick={() => {
                      onPick(o.path);
                      setOpen(false);
                      setQuery("");
                    }}
                  >
                    <code className="truncate font-mono text-xs text-fg">{`{{${o.path}}}`}</code>
                    {o.hint && t.has(`hints.${o.hint}`) ? (
                      <span className="shrink-0 text-[10px] text-fg-subtle">{t(`hints.${o.hint}`)}</span>
                    ) : null}
                  </button>
                ))}
              </div>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function insertAt(value: string, el: HTMLInputElement | HTMLTextAreaElement | null, text: string): string {
  if (!el) return value + text;
  const start = el.selectionStart ?? value.length;
  const end = el.selectionEnd ?? value.length;
  return value.slice(0, start) + text + value.slice(end);
}

/** Text with `{{bindings}}` (single line or multi-line) and a picker to insert them at the caret. */
export function TemplateField({
  id,
  value,
  onChange,
  options,
  multiline = false,
  rows = 3,
  placeholder,
  disabled,
  mono = false,
  invalid = false,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  options: BindingOption[] | null;
  multiline?: boolean;
  rows?: number;
  placeholder?: string;
  disabled?: boolean;
  mono?: boolean;
  invalid?: boolean;
}) {
  const ref = React.useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const pick = (path: string) => onChange(insertAt(value, ref.current, `{{${path}}}`));
  const className = cn(mono && "font-mono text-xs", invalid && "border-danger");
  return (
    <div className="space-y-1">
      {multiline ? (
        <Textarea
          id={id}
          ref={ref}
          value={value}
          rows={rows}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className={className}
          aria-invalid={invalid || undefined}
        />
      ) : (
        <Input
          id={id}
          ref={ref}
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className={className}
          aria-invalid={invalid || undefined}
        />
      )}
      {options && !disabled ? (
        <div className="flex justify-end">
          <BindingPicker options={options} onPick={pick} />
        </div>
      ) : null}
    </div>
  );
}

export function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** A value that is either text (with bindings) or JSON (objects/lists whose strings may contain bindings). */
export function ValueEditor({
  id,
  value,
  onChange,
  options,
  disabled,
  invalid,
}: {
  id: string;
  value: unknown;
  onChange: (value: unknown) => void;
  options: BindingOption[] | null;
  disabled?: boolean;
  invalid?: boolean;
}) {
  const t = useTranslations("workflows.panel");
  const structured = value !== null && typeof value === "object";
  const [mode, setMode] = React.useState<"text" | "json">(structured ? "json" : "text");
  const [draft, setDraft] = React.useState(() => (structured ? JSON.stringify(value, null, 2) : asText(value)));
  const [error, setError] = React.useState<string | null>(null);
  const lastExternal = React.useRef(value);

  React.useEffect(() => {
    if (value === lastExternal.current) return;
    lastExternal.current = value;
    const isStructured = value !== null && typeof value === "object";
    setMode(isStructured ? "json" : "text");
    setDraft(isStructured ? JSON.stringify(value, null, 2) : asText(value));
    setError(null);
  }, [value]);

  const emit = (next: unknown) => {
    lastExternal.current = next;
    onChange(next);
  };

  const switchMode = (next: string) => {
    if (next === mode) return;
    if (next === "json") {
      const text = asText(value);
      const initial = text.trim().startsWith("{") || text.trim().startsWith("[") ? text : JSON.stringify({ valor: text }, null, 2);
      setDraft(initial);
      setMode("json");
      try {
        emit(JSON.parse(initial));
        setError(null);
      } catch {
        setError(t("invalidJson"));
      }
    } else {
      setMode("text");
      const text = structured ? JSON.stringify(value) : asText(value);
      setDraft(text);
      emit(text);
      setError(null);
    }
  };

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <div className="w-32">
          <Select
            aria-label={t("valueMode")}
            value={mode}
            onValueChange={switchMode}
            disabled={disabled}
            options={[
              { value: "text", label: t("valueText") },
              { value: "json", label: t("valueJson") },
            ]}
          />
        </div>
        {mode === "json" && options && !disabled ? (
          <BindingPicker
            options={options}
            onPick={(path) => {
              const next = `${draft.trimEnd()}${draft.trim() ? "\n" : ""}"{{${path}}}"`;
              setDraft(next);
              try {
                emit(JSON.parse(next));
                setError(null);
              } catch {
                setError(t("invalidJson"));
              }
            }}
          />
        ) : null}
      </div>
      {mode === "text" ? (
        <TemplateField
          id={id}
          value={draft}
          multiline
          rows={3}
          options={options}
          disabled={disabled}
          invalid={invalid}
          onChange={(text) => {
            setDraft(text);
            emit(text);
          }}
        />
      ) : (
        <Textarea
          id={id}
          value={draft}
          rows={6}
          disabled={disabled}
          className={cn("font-mono text-xs", (error || invalid) && "border-danger")}
          aria-invalid={Boolean(error || invalid) || undefined}
          onChange={(e) => {
            setDraft(e.target.value);
            try {
              emit(JSON.parse(e.target.value));
              setError(null);
            } catch {
              setError(t("invalidJson"));
            }
          }}
        />
      )}
      {error ? <p className="text-xs text-danger">{error}</p> : null}
    </div>
  );
}

/** Key → value rows (arguments, payload, headers). Values may carry bindings unless `options` is null. */
export function KeyValueEditor({
  idPrefix,
  value,
  onChange,
  options,
  suggestions = [],
  disabled,
  keyPlaceholder,
  valuePlaceholder,
}: {
  idPrefix: string;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  options: BindingOption[] | null;
  suggestions?: string[];
  disabled?: boolean;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
}) {
  const t = useTranslations("workflows.panel");
  const entries = Object.entries(value);
  const [newKey, setNewKey] = React.useState("");
  const missing = suggestions.filter((s) => !(s in value));

  const rename = (from: string, to: string) => {
    if (!to || to === from || to in value) return;
    onChange(Object.fromEntries(entries.map(([k, v]) => (k === from ? [to, v] : [k, v]))));
  };

  const add = (key: string) => {
    const k = key.trim();
    if (!k || k in value) return;
    onChange({ ...value, [k]: "" });
    setNewKey("");
  };

  return (
    <div className="space-y-2">
      {entries.length === 0 ? <p className="text-xs text-fg-subtle">{t("noEntries")}</p> : null}
      {entries.map(([key, v], index) => (
        <div key={`${index}-${key}`} className="rounded-md border border-border p-2">
          <div className="flex items-center gap-1.5">
            <Input
              aria-label={t("key")}
              defaultValue={key}
              disabled={disabled}
              className="h-7 font-mono text-xs"
              onBlur={(e) => rename(key, e.target.value.trim())}
            />
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("removeEntry", { key })}
              disabled={disabled}
              onClick={() => onChange(Object.fromEntries(entries.filter(([k]) => k !== key)))}
            >
              <X />
            </Button>
          </div>
          <div className="mt-1.5">
            {typeof v === "string" || v === null || v === undefined ? (
              <TemplateField
                id={`${idPrefix}-${key}`}
                value={asText(v)}
                options={options}
                disabled={disabled}
                placeholder={valuePlaceholder}
                onChange={(next) => onChange({ ...value, [key]: next })}
              />
            ) : (
              <ValueEditor
                id={`${idPrefix}-${key}`}
                value={v}
                options={options}
                disabled={disabled}
                onChange={(next) => onChange({ ...value, [key]: next })}
              />
            )}
          </div>
        </div>
      ))}
      {!disabled ? (
        <div className="space-y-1.5">
          <div className="flex gap-1.5">
            <Input
              value={newKey}
              placeholder={keyPlaceholder ?? t("newKey")}
              className="h-7 font-mono text-xs"
              aria-label={t("newKey")}
              onChange={(e) => setNewKey(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  add(newKey);
                }
              }}
            />
            <Button size="sm" variant="secondary" onClick={() => add(newKey)} disabled={!newKey.trim()}>
              <Plus />
              {t("addEntry")}
            </Button>
          </div>
          {missing.length ? (
            <div className="flex flex-wrap gap-1">
              {missing.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => add(s)}
                  className="rounded-sm border border-dashed border-border px-1.5 py-0.5 font-mono text-[11px] text-fg-muted hover:border-border-strong hover:text-fg"
                >
                  + {s}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

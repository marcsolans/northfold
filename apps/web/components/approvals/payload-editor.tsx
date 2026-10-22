"use client";

import { Button, Field, Input, Select, Switch, Textarea } from "@messer/ui";
import { Braces, ListChecks } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import type { JsonSchema } from "@/lib/studio/types";

export interface PayloadEditorState {
  value: Record<string, unknown> | null;
  error: string | null;
}

type FieldKind = "string" | "text" | "number" | "integer" | "boolean" | "enum" | "json";

const LONG_TEXT_KEYS = /body|text|content|message|description|html|notes?/i;

function primaryType(schema: JsonSchema | undefined, value: unknown): string {
  const raw = schema?.type;
  const type = Array.isArray(raw) ? raw.find((x) => x !== "null") : raw;
  if (type) return type;
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "string" || value === undefined || value === null) return "string";
  return "object";
}

function kindOf(key: string, schema: JsonSchema | undefined, value: unknown): FieldKind {
  if (schema?.enum && schema.enum.length > 0) return "enum";
  const type = primaryType(schema, value);
  if (type === "string") {
    return LONG_TEXT_KEYS.test(key) || (typeof value === "string" && (value.length > 80 || value.includes("\n"))) ? "text" : "string";
  }
  if (type === "number" || type === "integer" || type === "boolean") return type;
  return "json";
}

function JsonField({
  id,
  value,
  onChange,
  invalidLabel,
}: {
  id: string;
  value: unknown;
  onChange: (value: unknown, error: string | null) => void;
  invalidLabel: string;
}) {
  const [text, setText] = React.useState(() => JSON.stringify(value ?? null, null, 2));
  return (
    <Textarea
      id={id}
      value={text}
      rows={4}
      className="font-mono text-xs"
      onChange={(e) => {
        setText(e.target.value);
        try {
          onChange(JSON.parse(e.target.value), null);
        } catch {
          onChange(value, invalidLabel);
        }
      }}
    />
  );
}

/**
 * Edit the values a tool will receive: a typed form generated from the tool's JSON Schema
 * (or from the payload itself), or raw JSON.
 */
export function PayloadEditor({
  idPrefix,
  payload,
  schema,
  onChange,
}: {
  idPrefix: string;
  payload: Record<string, unknown>;
  schema: JsonSchema | null;
  onChange: (state: PayloadEditorState) => void;
}) {
  const t = useTranslations("approvals.editor");
  const [mode, setMode] = React.useState<"form" | "json">("form");
  const [value, setValue] = React.useState<Record<string, unknown>>(payload);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [jsonText, setJsonText] = React.useState(() => JSON.stringify(payload, null, 2));
  const [jsonError, setJsonError] = React.useState<string | null>(null);

  const properties = schema?.properties ?? {};
  const keys = [...new Set([...Object.keys(properties), ...Object.keys(payload)])];
  const required = new Set(schema?.required ?? []);

  const emit = React.useCallback(
    (next: Record<string, unknown>, errors: Record<string, string>, jsonErr: string | null) => {
      const missing = (schema?.required ?? []).filter((k) => next[k] === undefined || next[k] === null || next[k] === "");
      const error = jsonErr ?? Object.values(errors)[0] ?? (missing.length ? t("missing", { fields: missing.join(", ") }) : null);
      onChange({ value: error ? null : next, error });
    },
    [onChange, t, schema],
  );

  const setField = (key: string, v: unknown, error: string | null = null) => {
    const next = { ...value, [key]: v };
    const errors = { ...fieldErrors };
    if (error) errors[key] = error;
    else delete errors[key];
    setValue(next);
    setFieldErrors(errors);
    setJsonText(JSON.stringify(next, null, 2));
    emit(next, errors, null);
  };

  const switchMode = (next: "form" | "json") => {
    if (next === "json") setJsonText(JSON.stringify(value, null, 2));
    if (next === "form" && jsonError) return;
    setMode(next);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end gap-1" role="group" aria-label={t("mode")}>
        <Button size="sm" variant={mode === "form" ? "secondary" : "ghost"} aria-pressed={mode === "form"} onClick={() => switchMode("form")}>
          <ListChecks />
          {t("form")}
        </Button>
        <Button size="sm" variant={mode === "json" ? "secondary" : "ghost"} aria-pressed={mode === "json"} onClick={() => switchMode("json")}>
          <Braces />
          {t("json")}
        </Button>
      </div>
      {mode === "json" ? (
        <Field label={t("jsonLabel")} htmlFor={`${idPrefix}-json`} error={jsonError}>
          <Textarea
            id={`${idPrefix}-json`}
            value={jsonText}
            rows={8}
            spellCheck={false}
            className="font-mono text-xs"
            aria-invalid={Boolean(jsonError) || undefined}
            onChange={(e) => {
              const text = e.target.value;
              setJsonText(text);
              try {
                const parsed: unknown = JSON.parse(text);
                if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
                const obj = parsed as Record<string, unknown>;
                setValue(obj);
                setJsonError(null);
                setFieldErrors({});
                emit(obj, {}, null);
              } catch {
                setJsonError(t("invalidJson"));
                emit(value, fieldErrors, t("invalidJson"));
              }
            }}
          />
        </Field>
      ) : (
        <div className="flex flex-col gap-3">
          {keys.map((key) => {
            const prop = properties[key];
            const current = value[key];
            const kind = kindOf(key, prop, payload[key]);
            const id = `${idPrefix}-${key}`;
            const label = (
              <>
                {prop?.title ?? key}
                {required.has(key) ? <span className="text-danger"> *</span> : null}
              </>
            );
            const hint = prop?.description;
            if (kind === "boolean") {
              return (
                <label key={key} htmlFor={id} className="flex items-center gap-2.5 text-sm">
                  <Switch id={id} checked={Boolean(current)} onCheckedChange={(c) => setField(key, c)} />
                  {label}
                </label>
              );
            }
            return (
              <Field key={key} label={label} htmlFor={id} hint={hint} error={fieldErrors[key]}>
                {kind === "enum" ? (
                  <Select
                    id={id}
                    aria-label={prop?.title ?? key}
                    value={current === undefined || current === null ? undefined : String(current)}
                    onValueChange={(v) => setField(key, (prop?.enum ?? []).find((opt) => String(opt) === v) ?? v)}
                    options={(prop?.enum ?? []).map((opt) => ({ value: String(opt), label: String(opt) }))}
                  />
                ) : kind === "text" ? (
                  <Textarea id={id} rows={3} value={typeof current === "string" ? current : ""} onChange={(e) => setField(key, e.target.value)} />
                ) : kind === "string" ? (
                  <Input id={id} value={typeof current === "string" ? current : current == null ? "" : String(current)} onChange={(e) => setField(key, e.target.value)} />
                ) : kind === "number" || kind === "integer" ? (
                  <Input
                    id={id}
                    inputMode={kind === "integer" ? "numeric" : "decimal"}
                    className="tabular"
                    defaultValue={current === undefined || current === null ? "" : String(current)}
                    onChange={(e) => {
                      const raw = e.target.value.trim().replace(",", ".");
                      if (raw === "") return setField(key, null);
                      const n = Number(raw);
                      if (!Number.isFinite(n) || (kind === "integer" && !Number.isInteger(n))) setField(key, current, t("invalidNumber"));
                      else setField(key, n);
                    }}
                  />
                ) : (
                  <JsonField id={id} value={current} invalidLabel={t("invalidJson")} onChange={(v, err) => setField(key, v, err)} />
                )}
              </Field>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Keys whose value differs from the original payload. */
export function changedFields(original: Record<string, unknown>, edited: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(edited)) {
    if (JSON.stringify(value) !== JSON.stringify(original[key])) out[key] = value;
  }
  return out;
}

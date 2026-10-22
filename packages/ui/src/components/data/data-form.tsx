"use client";

import { CheckCircle2 } from "lucide-react";
import * as React from "react";

import { cn } from "../../lib/cn";
import { Button } from "../button";
import { Checkbox } from "../form-controls";
import { Input, Textarea, inputClass } from "../input";
import { Field } from "../label";

export interface DataFormField {
  name: string;
  label: string;
  type?: "text" | "textarea" | "number" | "email" | "date" | "select" | "checkbox";
  required?: boolean;
  placeholder?: string | null;
  help?: string | null;
  options?: { value: string; label: string }[];
  default?: string | number | boolean | null;
  min?: number | null;
  max?: number | null;
  max_length?: number | null;
}

export type DataFormValues = Record<string, string | boolean>;

export interface DataFormLabels {
  submit: string;
  submitting: string;
  required: string;
  invalidEmail: string;
  invalidNumber: string;
  min: (n: number) => string;
  max: (n: number) => string;
  select: string;
  again: string;
}

export interface DataFormResult {
  ok: boolean;
  message?: string | null;
  field?: string | null;
}

function initial(fields: DataFormField[]): DataFormValues {
  const out: DataFormValues = {};
  for (const f of fields) {
    if (f.type === "checkbox") out[f.name] = f.default === true;
    else out[f.name] = f.default === null || f.default === undefined ? "" : String(f.default);
  }
  return out;
}

/** Form bound to a workflow or an agent. Client checks mirror the server's; server field errors are shown inline. */
export function DataForm({
  fields,
  submitLabel,
  successMessage,
  resetOnSubmit = true,
  onSubmit,
  disabled,
  labels,
  className,
}: {
  fields: DataFormField[];
  submitLabel?: string | null;
  successMessage?: string | null;
  resetOnSubmit?: boolean;
  onSubmit: (values: DataFormValues) => Promise<DataFormResult>;
  disabled?: boolean;
  labels: DataFormLabels;
  className?: string;
}) {
  const id = React.useId();
  const [values, setValues] = React.useState<DataFormValues>(() => initial(fields));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<DataFormResult | null>(null);

  const fieldsKey = React.useMemo(() => JSON.stringify(fields), [fields]);
  React.useEffect(() => {
    setValues(initial(JSON.parse(fieldsKey) as DataFormField[]));
    setErrors({});
  }, [fieldsKey]);

  const validate = (): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const f of fields) {
      const v = values[f.name];
      const empty = v === "" || v === undefined || (f.type === "checkbox" && v === false);
      if (f.required && empty) {
        out[f.name] = labels.required;
        continue;
      }
      if (empty || typeof v !== "string") continue;
      if (f.type === "email" && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.trim())) out[f.name] = labels.invalidEmail;
      if (f.type === "number") {
        const n = Number(v.replace(",", "."));
        if (!Number.isFinite(n)) out[f.name] = labels.invalidNumber;
        else if (f.min !== null && f.min !== undefined && n < f.min) out[f.name] = labels.min(f.min);
        else if (f.max !== null && f.max !== undefined && n > f.max) out[f.name] = labels.max(f.max);
      }
    }
    return out;
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setBusy(true);
    setResult(null);
    try {
      const res = await onSubmit(values);
      setResult(res);
      if (!res.ok && res.field) setErrors({ [res.field]: res.message ?? labels.required });
      if (res.ok && resetOnSubmit) setValues(initial(fields));
    } finally {
      setBusy(false);
    }
  };

  if (result?.ok && resetOnSubmit) {
    return (
      <div role="status" className={cn("flex flex-1 flex-col items-center justify-center gap-2 text-center", className)}>
        <CheckCircle2 className="size-6 text-success" aria-hidden />
        <p className="text-sm text-fg">{result.message || successMessage}</p>
        <Button size="sm" variant="secondary" onClick={() => setResult(null)}>
          {labels.again}
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} noValidate className={cn("flex flex-col gap-3", className)}>
      {fields.map((f) => {
        const fid = `${id}-${f.name}`;
        const value = values[f.name];
        const err = errors[f.name];
        const set = (v: string | boolean) => setValues((s) => ({ ...s, [f.name]: v }));
        const common = {
          id: fid,
          name: f.name,
          disabled: disabled || busy,
          "aria-invalid": err ? true : undefined,
          "aria-required": f.required || undefined,
        };
        if (f.type === "checkbox") {
          return (
            <div key={f.name} className="flex flex-col gap-1">
              <label htmlFor={fid} className="flex items-center gap-2 text-sm text-fg">
                <Checkbox {...common} checked={value === true} onCheckedChange={(c) => set(c === true)} />
                {f.label}
                {f.required ? <span className="text-danger" aria-hidden>*</span> : null}
              </label>
              {err ? <p className="text-xs text-danger" role="alert">{err}</p> : f.help ? <p className="text-xs text-fg-subtle">{f.help}</p> : null}
            </div>
          );
        }
        const label = (
          <>
            {f.label}
            {f.required ? <span className="ml-0.5 text-danger" aria-hidden>*</span> : null}
          </>
        );
        const text = typeof value === "string" ? value : "";
        return (
          <Field key={f.name} label={label} htmlFor={fid} hint={f.help ?? undefined} error={err}>
            {f.type === "textarea" ? (
              <Textarea {...common} value={text} placeholder={f.placeholder ?? undefined} maxLength={f.max_length ?? undefined} onChange={(e) => set(e.target.value)} />
            ) : f.type === "select" ? (
              <select {...common} value={text} onChange={(e) => set(e.target.value)} className={inputClass}>
                <option value="">{labels.select}</option>
                {(f.options ?? []).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                {...common}
                type={f.type === "number" ? "text" : f.type === "email" ? "email" : f.type === "date" ? "date" : "text"}
                inputMode={f.type === "number" ? "decimal" : undefined}
                value={text}
                placeholder={f.placeholder ?? undefined}
                maxLength={f.max_length ?? undefined}
                onChange={(e) => set(e.target.value)}
              />
            )}
          </Field>
        );
      })}
      {result && !result.ok && !result.field && result.message ? (
        <p role="alert" className="rounded-md border border-danger/25 bg-danger-soft px-3 py-2 text-sm text-danger">
          {result.message}
        </p>
      ) : null}
      {result?.ok && !resetOnSubmit ? (
        <p role="status" className="rounded-md border border-success/25 bg-success-soft px-3 py-2 text-sm text-success">
          {result.message || successMessage}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant="primary" loading={busy} disabled={disabled}>
          {busy ? labels.submitting : submitLabel || labels.submit}
        </Button>
      </div>
    </form>
  );
}

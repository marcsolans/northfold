"use client";

import { Field, Input, Select, Switch, Textarea, cn } from "@messer/ui";
import * as React from "react";

/** Compact controls of the properties panel. Every control is labelled (AA). */

export function Group({ title, children, actions }: { title: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-b border-border px-3 py-3 last:border-b-0">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-subtle">{title}</h3>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function TextField({
  label,
  value,
  onChange,
  placeholder,
  hint,
  error,
  mono,
  disabled,
}: {
  label: string;
  value: string | null | undefined;
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: string;
  error?: string | null;
  mono?: boolean;
  disabled?: boolean;
}) {
  const id = React.useId();
  return (
    <Field label={label} htmlFor={id} hint={hint} error={error ?? undefined}>
      <Input
        id={id}
        value={value ?? ""}
        placeholder={placeholder}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        onChange={(e) => onChange(e.target.value)}
        className={cn(mono && "font-mono text-xs")}
      />
    </Field>
  );
}

export function AreaField({
  label,
  value,
  onChange,
  placeholder,
  hint,
  error,
  mono,
  rows = 3,
}: {
  label: string;
  value: string | null | undefined;
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: string;
  error?: string | null;
  mono?: boolean;
  rows?: number;
}) {
  const id = React.useId();
  return (
    <Field label={label} htmlFor={id} hint={hint} error={error ?? undefined}>
      <Textarea
        id={id}
        rows={rows}
        value={value ?? ""}
        placeholder={placeholder}
        aria-invalid={error ? true : undefined}
        onChange={(e) => onChange(e.target.value)}
        className={cn("min-h-0", mono && "font-mono text-xs")}
      />
    </Field>
  );
}

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  nullable = false,
  hint,
}: {
  label: string;
  value: number | null | undefined;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  nullable?: boolean;
  hint?: string;
}) {
  const id = React.useId();
  const [text, setText] = React.useState(value === null || value === undefined ? "" : String(value));
  React.useEffect(() => {
    setText((prev) => {
      const parsed = prev.trim() === "" ? null : Number(prev.replace(",", "."));
      return parsed === (value ?? null) ? prev : value === null || value === undefined ? "" : String(value);
    });
  }, [value]);
  return (
    <Field label={label} htmlFor={id} hint={hint}>
      <Input
        id={id}
        inputMode="decimal"
        value={text}
        onChange={(e) => {
          const raw = e.target.value;
          setText(raw);
          if (raw.trim() === "") {
            if (nullable) onChange(null);
            return;
          }
          const n = Number(raw.replace(",", "."));
          if (!Number.isFinite(n)) return;
          const bounded = Math.min(max ?? Infinity, Math.max(min ?? -Infinity, n));
          onChange(bounded);
        }}
      />
    </Field>
  );
}

export function SelectField<T extends string>({
  label,
  value,
  onChange,
  options,
  placeholder,
  hint,
}: {
  label: string;
  value: T | null | undefined;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
  placeholder?: string;
  hint?: string;
}) {
  const id = React.useId();
  return (
    <Field label={label} htmlFor={id} hint={hint}>
      <Select id={id} value={value ?? undefined} onValueChange={(v) => onChange(v as T)} options={options} placeholder={placeholder} aria-label={label} />
    </Field>
  );
}

export function SwitchField({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  hint?: string;
}) {
  const id = React.useId();
  return (
    <div className="flex items-start justify-between gap-3">
      <label htmlFor={id} className="text-sm text-fg">
        {label}
        {hint ? <span className="block text-xs text-fg-subtle">{hint}</span> : null}
      </label>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

/** Comma- or line-separated list. */
export function ListField({
  label,
  value,
  onChange,
  separator = ",",
  hint,
  placeholder,
}: {
  label: string;
  value: string[] | undefined;
  onChange: (value: string[]) => void;
  separator?: "," | "\n";
  hint?: string;
  placeholder?: string;
}) {
  const [text, setText] = React.useState((value ?? []).join(separator === "," ? ", " : "\n"));
  const joined = (value ?? []).join("\u0000");
  React.useEffect(() => {
    setText((prev) => {
      const parsed = prev
        .split(separator)
        .map((s) => s.trim())
        .filter(Boolean)
        .join("\u0000");
      return parsed === joined ? prev : joined.split("\u0000").filter(Boolean).join(separator === "," ? ", " : "\n");
    });
  }, [joined, separator]);
  const update = (raw: string) => {
    setText(raw);
    onChange(
      raw
        .split(separator)
        .map((s) => s.trim())
        .filter(Boolean),
    );
  };
  return separator === "," ? (
    <TextField label={label} value={text} onChange={update} hint={hint} placeholder={placeholder} />
  ) : (
    <AreaField label={label} value={text} onChange={update} hint={hint} placeholder={placeholder} rows={4} />
  );
}

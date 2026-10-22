"use client";

import { Badge, Input, cn } from "@messer/ui";
import { X } from "lucide-react";
import * as React from "react";

/** A titled block of the configuration form. */
export function Section({
  id,
  title,
  description,
  actions,
  children,
}: {
  id: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-title`} className="border-b border-border px-4 py-5 last:border-b-0 md:px-5">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={`${id}-title`} className="text-base font-semibold">
            {title}
          </h2>
          {description ? <p className="mt-0.5 text-xs text-fg-muted">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  );
}

/** Number input that tolerates partial typing; empty → `null` when `nullable`. */
export function NumberInput({
  id,
  value,
  onChange,
  nullable = false,
  step,
  min,
  max,
  disabled,
  placeholder,
  invalid,
  integer = true,
}: {
  id: string;
  value: number | null;
  onChange: (value: number | null) => void;
  nullable?: boolean;
  step?: number;
  min?: number;
  max?: number;
  disabled?: boolean;
  placeholder?: string;
  invalid?: boolean;
  integer?: boolean;
}) {
  const [text, setText] = React.useState(value === null ? "" : String(value));
  React.useEffect(() => {
    setText((prev) => {
      const parsed = prev.trim() === "" ? null : Number(prev.replace(",", "."));
      return parsed === value ? prev : value === null ? "" : String(value);
    });
  }, [value]);
  return (
    <Input
      id={id}
      inputMode={integer ? "numeric" : "decimal"}
      value={text}
      step={step}
      min={min}
      max={max}
      disabled={disabled}
      placeholder={placeholder}
      aria-invalid={invalid || undefined}
      className="tabular"
      onChange={(e) => {
        const raw = e.target.value;
        setText(raw);
        if (raw.trim() === "") {
          if (nullable) onChange(null);
          return;
        }
        const n = Number(raw.replace(",", "."));
        if (Number.isFinite(n)) onChange(integer ? Math.trunc(n) : n);
      }}
    />
  );
}

/** Chips with free text entry (Enter or comma adds). */
export function TagInput({
  id,
  values,
  onChange,
  placeholder,
  disabled,
  removeLabel,
}: {
  id: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  removeLabel: (value: string) => string;
}) {
  const [text, setText] = React.useState("");
  const add = (raw: string) => {
    const parts = raw
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean)
      .filter((p) => !values.includes(p));
    if (parts.length) onChange([...values, ...parts]);
    setText("");
  };
  return (
    <div
      className={cn(
        "flex min-h-8 flex-wrap items-center gap-1 rounded-md border border-border bg-surface px-1.5 py-1",
        disabled && "opacity-60",
      )}
    >
      {values.map((v) => (
        <Badge key={v} tone="neutral" className="gap-0.5">
          {v}
          {disabled ? null : (
            <button
              type="button"
              className="rounded-sm p-0.5 hover:bg-muted"
              aria-label={removeLabel(v)}
              onClick={() => onChange(values.filter((x) => x !== v))}
            >
              <X className="size-3" />
            </button>
          )}
        </Badge>
      ))}
      <input
        id={id}
        value={text}
        disabled={disabled}
        placeholder={values.length === 0 ? placeholder : undefined}
        className="h-6 min-w-32 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-fg-subtle"
        onChange={(e) => {
          const v = e.target.value;
          if (v.includes(",")) add(v);
          else setText(v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add(text);
          } else if (e.key === "Backspace" && !text && values.length) {
            onChange(values.slice(0, -1));
          }
        }}
        onBlur={() => text.trim() && add(text)}
      />
    </div>
  );
}

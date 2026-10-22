"use client";

import { Search } from "lucide-react";
import * as React from "react";

import { cn } from "../../lib/cn";
import { Input, inputClass } from "../input";

export interface FilterOption {
  value: string;
  label: string;
}

export interface FilterDef {
  name: string;
  label: string;
  type?: "text" | "select" | "date" | "number";
  options?: FilterOption[];
  /** No empty ("all") choice for selects, e.g. when the filter has a default value. */
  required?: boolean;
}

export type FilterValues = Record<string, string>;

/** Inputs above a table, list or chart. Values are sent to the server as bound parameters. */
export function FilterBar({
  filters,
  values,
  onChange,
  search,
  onSearchChange,
  labels,
  className,
}: {
  filters: FilterDef[];
  values: FilterValues;
  onChange: (values: FilterValues) => void;
  search?: string;
  onSearchChange?: (value: string) => void;
  labels: { search: string; all: string };
  className?: string;
}) {
  const id = React.useId();
  if (filters.length === 0 && !onSearchChange) return null;
  return (
    <div className={cn("flex flex-wrap items-end gap-2", className)}>
      {onSearchChange ? (
        <div className="relative min-w-40 flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-fg-subtle" aria-hidden />
          <Input
            type="search"
            value={search ?? ""}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={labels.search}
            aria-label={labels.search}
            className="pl-7"
          />
        </div>
      ) : null}
      {filters.map((f) => {
        const inputId = `${id}-${f.name}`;
        const value = values[f.name] ?? "";
        const set = (v: string) => onChange({ ...values, [f.name]: v });
        return (
          <label key={f.name} htmlFor={inputId} className="flex min-w-32 flex-col gap-1 text-xs font-medium text-fg-muted">
            {f.label}
            {f.type === "select" ? (
              <select id={inputId} value={value} onChange={(e) => set(e.target.value)} className={cn(inputClass, "pr-6")}>
                {f.required ? null : <option value="">{labels.all}</option>}
                {(f.options ?? []).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                id={inputId}
                type={f.type === "date" ? "date" : f.type === "number" ? "number" : "text"}
                value={value}
                onChange={(e) => set(e.target.value)}
              />
            )}
          </label>
        );
      })}
    </div>
  );
}

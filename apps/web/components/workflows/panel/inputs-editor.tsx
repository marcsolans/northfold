"use client";

import { Button, Checkbox, Input, Select } from "@messer/ui";
import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { isValidId } from "@/lib/workflows/graph";
import type { InputType, WorkflowInput } from "@/lib/workflows/types";

const TYPES: InputType[] = ["string", "number", "boolean", "object"];

/** The workflow's declared inputs (what a manual run asks for; triggers add `event`). */
export function InputsEditor({
  inputs,
  onChange,
  disabled,
}: {
  inputs: WorkflowInput[];
  onChange: (inputs: WorkflowInput[]) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("workflows.inputs");
  const update = (index: number, patch: Partial<WorkflowInput>) =>
    onChange(inputs.map((input, i) => (i === index ? { ...input, ...patch } : input)));
  const add = () => {
    const names = new Set(inputs.map((i) => i.name));
    let n = inputs.length + 1;
    while (names.has(`campo_${n}`)) n += 1;
    onChange([...inputs, { name: `campo_${n}`, type: "string", description: "", required: false }]);
  };
  return (
    <div className="space-y-2">
      <p className="text-[11px] leading-4 text-fg-subtle">{t("hint")}</p>
      {inputs.length === 0 ? <p className="text-xs text-fg-subtle">{t("empty")}</p> : null}
      {inputs.map((input, index) => {
        const duplicate = inputs.findIndex((i) => i.name === input.name) !== index;
        const invalid = !isValidId(input.name) || duplicate;
        return (
          <div key={index} className="space-y-1.5 rounded-md border border-border p-2">
            <div className="flex gap-1.5">
              <Input
                aria-label={t("name")}
                value={input.name}
                disabled={disabled}
                className="h-7 font-mono text-xs"
                aria-invalid={invalid || undefined}
                onChange={(e) => update(index, { name: e.target.value.trim() })}
              />
              <div className="w-28 shrink-0">
                <Select
                  aria-label={t("type")}
                  value={input.type}
                  disabled={disabled}
                  onValueChange={(v) => update(index, { type: v as InputType })}
                  options={TYPES.map((type) => ({ value: type, label: t(`types.${type}`) }))}
                />
              </div>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("remove", { name: input.name })}
                disabled={disabled}
                onClick={() => onChange(inputs.filter((_, i) => i !== index))}
              >
                <Trash2 />
              </Button>
            </div>
            {invalid ? <p className="text-xs text-danger">{duplicate ? t("duplicate") : t("invalidName")}</p> : null}
            <Input
              aria-label={t("description")}
              placeholder={t("description")}
              value={input.description}
              disabled={disabled}
              className="h-7 text-xs"
              onChange={(e) => update(index, { description: e.target.value })}
            />
            <label className="flex items-center gap-2 text-xs text-fg-muted">
              <Checkbox
                checked={input.required}
                disabled={disabled}
                onCheckedChange={(checked) => update(index, { required: checked === true })}
              />
              {t("required")}
            </label>
          </div>
        );
      })}
      {!disabled ? (
        <Button size="sm" variant="secondary" onClick={add}>
          <Plus />
          {t("add")}
        </Button>
      ) : null}
    </div>
  );
}

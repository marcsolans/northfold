"use client";

import { Input, Select } from "@messer/ui";
import { useTranslations } from "next-intl";
import * as React from "react";

import { CRON_PRESETS, type CronFields, buildCron, invalidCronFields, parseCron, presetOf, timeZones } from "@/lib/workflows/cron";

const FIELDS: (keyof CronFields)[] = ["minute", "hour", "day", "month", "weekday"];

/** Visual cron editor: presets, the five fields and the time zone the schedule is evaluated in. */
export function CronPicker({
  expression,
  timezone,
  onChange,
  disabled,
}: {
  expression: string;
  timezone: string;
  onChange: (value: { expression: string; timezone: string; valid: boolean }) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("workflows.cron");
  const fields = parseCron(expression) ?? { minute: "0", hour: "9", day: "*", month: "*", weekday: "1-5" };
  const invalid = invalidCronFields(fields);
  const preset = presetOf(expression) ?? "custom";
  const zones = React.useMemo(() => timeZones(), []);

  const emit = (next: CronFields, zone = timezone) =>
    onChange({ expression: buildCron(next), timezone: zone, valid: invalidCronFields(next).length === 0 });

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <label htmlFor="cron-preset" className="text-xs font-medium">
          {t("frequency")}
        </label>
        <Select
          id="cron-preset"
          value={preset}
          disabled={disabled}
          onValueChange={(key) => {
            const found = CRON_PRESETS.find((p) => p.key === key);
            if (found) emit(parseCron(found.expression) as CronFields);
          }}
          options={[
            ...CRON_PRESETS.map((p) => ({ value: p.key, label: t(`presets.${p.key}`), description: p.expression })),
            { value: "custom", label: t("presets.custom") },
          ]}
        />
      </div>
      <div className="grid grid-cols-5 gap-1.5">
        {FIELDS.map((key) => (
          <div key={key} className="space-y-1">
            <label htmlFor={`cron-${key}`} className="block truncate text-[11px] text-fg-muted">
              {t(`fields.${key}`)}
            </label>
            <Input
              id={`cron-${key}`}
              value={fields[key]}
              disabled={disabled}
              className="h-7 px-1.5 text-center font-mono text-xs"
              aria-invalid={invalid.includes(key) || undefined}
              onChange={(e) => emit({ ...fields, [key]: e.target.value })}
            />
          </div>
        ))}
      </div>
      <p className="text-[11px] leading-4 text-fg-subtle">{t("syntax")}</p>
      {invalid.length ? <p className="text-xs text-danger">{t("invalid")}</p> : null}
      <div className="space-y-1">
        <label htmlFor="cron-timezone" className="text-xs font-medium">
          {t("timezone")}
        </label>
        <Select
          id="cron-timezone"
          value={timezone}
          disabled={disabled}
          onValueChange={(zone) => emit(fields, zone)}
          options={zones.map((z) => ({ value: z, label: z }))}
        />
      </div>
      <p className="font-mono text-xs text-fg-muted">
        {buildCron(fields)} · {timezone}
      </p>
    </div>
  );
}

"use client";

import { ConfirmDialog, Field, Input } from "@messer/ui";
import { useTranslations } from "next-intl";
import * as React from "react";

/** Destructive confirmation that requires typing ``expected`` (an identifier or an email). */
export function TypedConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  expected,
  confirmLabel,
  loading,
  error,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  expected: string;
  confirmLabel: string;
  loading?: boolean;
  error?: string | null;
  onConfirm: (typed: string) => void;
}) {
  const t = useTranslations("enterprise");
  const tc = useTranslations("common");
  const [value, setValue] = React.useState("");
  const [mismatch, setMismatch] = React.useState(false);
  const id = React.useId();

  React.useEffect(() => {
    if (open) {
      setValue("");
      setMismatch(false);
    }
  }, [open]);

  const matches = value.trim().toLowerCase() === expected.trim().toLowerCase();
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      confirmLabel={confirmLabel}
      cancelLabel={tc("cancel")}
      loading={loading}
      onConfirm={() => {
        if (!matches) {
          setMismatch(true);
          return;
        }
        onConfirm(value.trim());
      }}
    >
      <Field
        label={t("typeToConfirm", { value: expected })}
        htmlFor={id}
        error={mismatch && !matches ? t("typeMismatch") : (error ?? undefined)}
      >
        <Input
          id={id}
          value={value}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={mismatch && !matches}
          onChange={(e) => {
            setValue(e.target.value);
            setMismatch(false);
          }}
        />
      </Field>
    </ConfirmDialog>
  );
}

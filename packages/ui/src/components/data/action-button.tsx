"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import * as React from "react";

import { cn } from "../../lib/cn";
import { Button } from "../button";
import { ConfirmDialog } from "../dialog";

export interface ActionOutcome {
  ok: boolean;
  message?: string | null;
}

/** Button that runs a workflow or an agent, with an optional confirmation and the outcome below it. */
export function ActionButton({
  label,
  variant = "primary",
  description,
  confirm,
  onRun,
  disabled,
  labels,
  className,
}: {
  label: string;
  variant?: "primary" | "secondary" | "danger";
  description?: string | null;
  confirm?: string | null;
  onRun: () => Promise<ActionOutcome>;
  disabled?: boolean;
  labels: { confirmTitle: string; confirm: string; cancel: string };
  className?: string;
}) {
  const [busy, setBusy] = React.useState(false);
  const [asking, setAsking] = React.useState(false);
  const [outcome, setOutcome] = React.useState<ActionOutcome | null>(null);

  const run = async () => {
    setBusy(true);
    setOutcome(null);
    try {
      setOutcome(await onRun());
    } finally {
      setBusy(false);
      setAsking(false);
    }
  };

  return (
    <div className={cn("flex flex-col items-start gap-2", className)}>
      {description ? <p className="text-sm text-fg-muted">{description}</p> : null}
      <Button variant={variant} loading={busy} disabled={disabled} onClick={() => (confirm ? setAsking(true) : void run())}>
        {label}
      </Button>
      {outcome?.message ? (
        <p role={outcome.ok ? "status" : "alert"} className={cn("flex items-start gap-1.5 text-sm", outcome.ok ? "text-fg" : "text-danger")}>
          {outcome.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden /> : <XCircle className="mt-0.5 size-4 shrink-0" aria-hidden />}
          <span className="whitespace-pre-wrap">{outcome.message}</span>
        </p>
      ) : null}
      {confirm ? (
        <ConfirmDialog
          open={asking}
          onOpenChange={setAsking}
          title={labels.confirmTitle}
          description={confirm}
          confirmLabel={labels.confirm}
          cancelLabel={labels.cancel}
          destructive={variant === "danger"}
          loading={busy}
          onConfirm={run}
        />
      ) : null}
    </div>
  );
}

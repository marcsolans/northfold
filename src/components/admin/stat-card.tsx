import { type ReactNode } from "react";

import { Card } from "@/components/ui/card";

export function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <Card className="p-5">
      <p className="text-xs font-medium tracking-[0.15em] text-muted-foreground uppercase">
        {label}
      </p>
      <p className="mt-3 text-2xl font-light tracking-tight tabular-nums">{value}</p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </Card>
  );
}

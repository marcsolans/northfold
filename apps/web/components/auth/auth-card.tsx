import type * as React from "react";

export function AuthCard({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: React.ReactNode; footer?: React.ReactNode }) {
  return (
    <div>
      <div className="rounded-md border border-border bg-surface p-6">
        <h1 className="text-lg font-semibold">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-fg-muted">{subtitle}</p> : null}
        <div className="mt-5">{children}</div>
      </div>
      {footer ? <div className="mt-4 text-center text-sm text-fg-muted">{footer}</div> : null}
    </div>
  );
}

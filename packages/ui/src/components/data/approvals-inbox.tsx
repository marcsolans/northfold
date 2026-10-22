"use client";

import { Check, X } from "lucide-react";
import * as React from "react";

import { cn } from "../../lib/cn";
import { Badge } from "../badge";
import { Button } from "../button";
import { ConfirmDialog } from "../dialog";
import { Textarea } from "../input";
import { Skeleton } from "../skeleton";
import { DataStatus, type DataStateLabels } from "./data-state";

export interface ApprovalItem {
  id: string;
  title: string;
  workforce_name: string;
  tool_name: string;
  payload: Record<string, unknown>;
  status: string;
  created_at: string | null;
  expires_at: string | null;
  can_decide: boolean;
}

export interface ApprovalsInboxLabels extends DataStateLabels {
  approve: string;
  deny: string;
  approveTitle: string;
  denyTitle: string;
  comment: string;
  cancel: string;
  status: (status: string) => string;
  expires: (when: string) => string;
  noPermission: string;
}

/** Pending approvals of the project with approve / deny (each decision asks for confirmation). */
export function ApprovalsInbox({
  items,
  pageSize = 10,
  loading,
  error,
  onRetry,
  onDecide,
  labels,
  locale = "es-ES",
  className,
}: {
  items: ApprovalItem[];
  pageSize?: number;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onDecide: (id: string, decision: "approve" | "deny", comment: string | null) => Promise<void>;
  labels: ApprovalsInboxLabels;
  locale?: string;
  className?: string;
}) {
  const [pending, setPending] = React.useState<{ item: ApprovalItem; decision: "approve" | "deny" } | null>(null);
  const [comment, setComment] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const commentId = React.useId();
  const when = (iso: string | null) =>
    iso ? new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(new Date(iso)) : "";

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col", className)}>
      <DataStatus
        loading={loading}
        error={error}
        empty={!loading && !error && items.length === 0}
        labels={labels}
        onRetry={onRetry}
        skeleton={Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      >
        <ul className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto">
          {items.slice(0, pageSize).map((item) => (
            <li key={item.id} className="rounded-md border border-border px-3 py-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-fg">{item.title}</p>
                  <p className="truncate text-xs text-fg-muted">
                    {item.workforce_name} · {item.tool_name} · {when(item.created_at)}
                  </p>
                </div>
                <Badge tone={item.status === "pending" ? "warning" : item.status === "approved" ? "success" : "neutral"}>
                  {labels.status(item.status)}
                </Badge>
              </div>
              {Object.keys(item.payload).length > 0 ? (
                <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                  {Object.entries(item.payload)
                    .slice(0, 6)
                    .map(([k, v]) => (
                      <React.Fragment key={k}>
                        <dt className="text-fg-subtle">{k}</dt>
                        <dd className="truncate text-fg">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
                      </React.Fragment>
                    ))}
                </dl>
              ) : null}
              {item.status === "pending" ? (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {item.can_decide ? (
                    <>
                      <Button size="sm" variant="primary" onClick={() => setPending({ item, decision: "approve" })}>
                        <Check />
                        {labels.approve}
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => setPending({ item, decision: "deny" })}>
                        <X />
                        {labels.deny}
                      </Button>
                    </>
                  ) : (
                    <span className="text-xs text-fg-subtle">{labels.noPermission}</span>
                  )}
                  {item.expires_at ? <span className="ml-auto text-xs text-fg-subtle">{labels.expires(when(item.expires_at))}</span> : null}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </DataStatus>
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPending(null);
            setComment("");
          }
        }}
        title={pending?.decision === "approve" ? labels.approveTitle : labels.denyTitle}
        description={pending?.item.title}
        confirmLabel={pending?.decision === "approve" ? labels.approve : labels.deny}
        cancelLabel={labels.cancel}
        destructive={pending?.decision === "deny"}
        loading={busy}
        onConfirm={async () => {
          if (!pending) return;
          setBusy(true);
          try {
            await onDecide(pending.item.id, pending.decision, comment.trim() || null);
            setPending(null);
            setComment("");
          } finally {
            setBusy(false);
          }
        }}
      >
        <label htmlFor={commentId} className="text-sm font-medium text-fg">
          {labels.comment}
        </label>
        <Textarea id={commentId} value={comment} onChange={(e) => setComment(e.target.value)} maxLength={4000} className="mt-1.5" />
      </ConfirmDialog>
    </div>
  );
}

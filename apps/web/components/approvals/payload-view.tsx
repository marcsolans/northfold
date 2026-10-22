"use client";

import { cn } from "@messer/ui";
import { useTranslations } from "next-intl";

import { JsonView } from "@/components/studio/json-view";
import type { JsonSchema } from "@/lib/studio/types";

function isFlat(payload: Record<string, unknown>): boolean {
  return Object.values(payload).every((v) => v === null || ["string", "number", "boolean"].includes(typeof v));
}

/** What the tool would receive: a readable key/value list for flat payloads, a JSON tree otherwise. */
export function PayloadView({
  payload,
  schema,
  changes,
  className,
}: {
  payload: Record<string, unknown>;
  schema?: JsonSchema | null;
  /** Corrected values (approve with changes) shown next to the originals. */
  changes?: Record<string, unknown> | null;
  className?: string;
}) {
  const t = useTranslations("approvals.payload");
  const entries = Object.entries(payload);
  if (entries.length === 0) return <p className={cn("text-xs text-fg-subtle", className)}>{t("empty")}</p>;
  if (!isFlat(payload)) return <JsonView value={payload} className={className} />;
  return (
    <dl className={cn("divide-y divide-border rounded-md border border-border bg-surface text-sm", className)}>
      {entries.map(([key, value]) => {
        const label = schema?.properties?.[key]?.title ?? key;
        const changed = changes && key in changes ? changes[key] : undefined;
        return (
          <div key={key} className="grid gap-1 px-3 py-2 sm:grid-cols-[9rem_1fr]">
            <dt className="text-xs font-medium text-fg-muted">{label}</dt>
            <dd className="min-w-0 whitespace-pre-wrap break-words">
              {changed !== undefined ? (
                <>
                  <span className="text-fg-subtle line-through">{String(value ?? "")}</span>{" "}
                  <span className="font-medium">{String(changed ?? "")}</span>
                </>
              ) : value === null || value === "" ? (
                <span className="text-fg-subtle">—</span>
              ) : (
                String(value)
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

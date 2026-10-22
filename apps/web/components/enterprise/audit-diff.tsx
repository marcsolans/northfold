"use client";

import { CodeBlock, TBody, TD, TH, THead, TR, Table, cn } from "@messer/ui";
import { useTranslations } from "next-intl";

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

function isRecord(value: unknown): value is Record<string, Json> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function show(value: Json | undefined): string {
  if (value === undefined) return "—";
  if (value === null) return "null";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** Field-by-field view of an audit entry's ``diff`` ({before, after} or a flat object), plus the raw JSON. */
export function AuditDiff({ diff }: { diff: Record<string, unknown> }) {
  const t = useTranslations("audit.diff");
  const before = diff.before as Json | undefined;
  const after = diff.after as Json | undefined;
  const hasPair = "before" in diff || "after" in diff;
  const rest = Object.fromEntries(Object.entries(diff).filter(([k]) => k !== "before" && k !== "after")) as Record<string, Json>;

  let rows: { field: string; before?: Json; after?: Json; changed: boolean }[] = [];
  if (hasPair && (isRecord(before) || isRecord(after))) {
    const b = isRecord(before) ? before : {};
    const a = isRecord(after) ? after : {};
    rows = Array.from(new Set([...Object.keys(b), ...Object.keys(a)]))
      .sort()
      .map((field) => ({ field, before: b[field], after: a[field], changed: JSON.stringify(b[field]) !== JSON.stringify(a[field]) }));
  } else if (hasPair) {
    rows = [{ field: "value", before, after, changed: JSON.stringify(before) !== JSON.stringify(after) }];
  }

  if (Object.keys(diff).length === 0) return <p className="text-sm text-fg-subtle">{t("noChanges")}</p>;

  return (
    <div className="flex flex-col gap-4">
      {rows.length > 0 ? (
        <Table>
          <THead>
            <tr>
              <TH>{t("field")}</TH>
              <TH>{t("before")}</TH>
              <TH>{t("after")}</TH>
            </tr>
          </THead>
          <TBody>
            {rows.map((r) => (
              <TR key={r.field}>
                <TD className="font-mono text-xs">{r.field}</TD>
                <TD className={cn("break-all font-mono text-xs", r.changed && "bg-danger-soft text-danger")}>{show(r.before)}</TD>
                <TD className={cn("break-all font-mono text-xs", r.changed && "bg-success-soft text-success")}>{show(r.after)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      ) : null}
      {Object.keys(rest).length > 0 ? (
        <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[12rem_1fr]">
          {Object.entries(rest).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="font-mono text-xs text-fg-muted">{k}</dt>
              <dd className="break-all font-mono text-xs">{show(v)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <details>
        <summary className="cursor-pointer text-xs text-fg-muted">{t("raw")}</summary>
        <CodeBlock className="mt-2" language="json" code={JSON.stringify(diff, null, 2)} />
      </details>
    </div>
  );
}

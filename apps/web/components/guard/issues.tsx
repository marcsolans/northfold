"use client";

import { cn } from "@messer/ui";
import { AlertTriangle, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import type { Issue } from "./types";

/** Localized text of a validation issue (known codes are translated; schema errors keep the server text). */
export function useIssueText(): (issue: Issue) => string {
  const t = useTranslations("guard.editor.issues.codes");
  return React.useCallback(
    (issue: Issue) => {
      const params = Object.fromEntries(
        Object.entries(issue.params ?? {}).map(([k, v]) => [k, typeof v === "number" ? v : String(v)]),
      ) as Record<string, string | number>;
      return t.has(issue.code) ? t(issue.code, params) : issue.message;
    },
    [t],
  );
}

export function IssueList({ issues, className }: { issues: Issue[]; className?: string }) {
  const text = useIssueText();
  if (issues.length === 0) return null;
  return (
    <ul className={cn("flex flex-col gap-1", className)}>
      {issues.map((issue, i) => (
        <li
          key={`${issue.path}-${issue.code}-${i}`}
          className={cn("flex items-start gap-1.5 text-xs", issue.level === "error" ? "text-danger" : "text-warning")}
          role={issue.level === "error" ? "alert" : undefined}
        >
          {issue.level === "error" ? (
            <XCircle className="mt-px size-3.5 shrink-0" aria-hidden />
          ) : (
            <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden />
          )}
          <span>{text(issue)}</span>
        </li>
      ))}
    </ul>
  );
}

"use client";

import { Badge, Button, Checkbox, Input, Popover, PopoverContent, PopoverTrigger, Skeleton, cn } from "@messer/ui";
import { BookOpen, ChevronDown, X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useKnowledgeBases } from "./queries";

/**
 * Pick one or more knowledge bases of the organization (e.g. for an agent's knowledge tools).
 * Controlled: ``value`` is the list of selected ids. With ``multiple={false}`` at most one is kept.
 */
export function KnowledgeBasePicker({
  value,
  onChange,
  multiple = true,
  projectId,
  disabled,
  className,
  id,
}: {
  value: string[];
  onChange: (ids: string[]) => void;
  multiple?: boolean;
  projectId?: string | null;
  disabled?: boolean;
  className?: string;
  id?: string;
}) {
  const t = useTranslations("knowledge.picker");
  const kbs = useKnowledgeBases();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const all = (kbs.data ?? []).filter((kb) => !projectId || kb.project_id === null || kb.project_id === projectId);
  const byId = new Map(all.map((kb) => [kb.id, kb]));
  const filtered = all.filter((kb) => !query.trim() || kb.name.toLowerCase().includes(query.trim().toLowerCase()));

  const toggle = (kbId: string) => {
    if (value.includes(kbId)) onChange(value.filter((v) => v !== kbId));
    else onChange(multiple ? [...value, kbId] : [kbId]);
    if (!multiple) setOpen(false);
  };

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            id={id}
            type="button"
            disabled={disabled}
            className="flex h-8 w-full items-center justify-between gap-2 rounded-md border border-border bg-surface px-2.5 text-left text-sm text-fg disabled:opacity-60"
            aria-haspopup="listbox"
            aria-expanded={open}
          >
            <span className={cn("truncate", value.length === 0 && "text-fg-subtle")}>
              {value.length === 0
                ? t("placeholder")
                : value.length === 1
                  ? (byId.get(value[0] ?? "")?.name ?? t("selected", { count: 1 }))
                  : t("selected", { count: value.length })}
            </span>
            <ChevronDown className="size-4 shrink-0 text-fg-subtle" aria-hidden />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] min-w-64 p-0">
          <div className="border-b border-border p-2">
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("search")} aria-label={t("search")} autoFocus />
          </div>
          <div className="max-h-64 overflow-y-auto p-1" role="listbox" aria-multiselectable={multiple}>
            {kbs.isLoading ? (
              <div className="flex flex-col gap-1 p-1">
                <Skeleton className="h-7" />
                <Skeleton className="h-7" />
              </div>
            ) : kbs.error ? (
              <p className="p-2 text-xs text-danger">{t("error")}</p>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-start gap-2 p-2 text-xs text-fg-muted">
                {all.length === 0 ? t("empty") : t("noMatches")}
                {all.length === 0 ? (
                  <Button asChild size="sm" variant="secondary">
                    <Link href="/app/knowledge">{t("create")}</Link>
                  </Button>
                ) : null}
              </div>
            ) : (
              filtered.map((kb) => {
                const checked = value.includes(kb.id);
                return (
                  <label
                    key={kb.id}
                    role="option"
                    aria-selected={checked}
                    className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-subtle"
                  >
                    <Checkbox checked={checked} onCheckedChange={() => toggle(kb.id)} aria-label={kb.name} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{kb.name}</span>
                      <span className="block text-xs text-fg-subtle">
                        {t("summary", { files: kb.stats.files, tables: kb.stats.tables })}
                      </span>
                    </span>
                  </label>
                );
              })
            )}
          </div>
        </PopoverContent>
      </Popover>
      {multiple && value.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {value.map((kbId) => (
            <Badge key={kbId} tone="neutral" className="gap-1">
              <BookOpen className="size-3" aria-hidden />
              {byId.get(kbId)?.name ?? t("unknown")}
              <button type="button" onClick={() => toggle(kbId)} aria-label={t("remove")} className="text-fg-subtle hover:text-fg">
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  );
}

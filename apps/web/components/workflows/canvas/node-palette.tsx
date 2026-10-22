"use client";

import { Input, cn } from "@messer/ui";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import type { CustomFunction, NodeType, PaletteNodeType } from "@/lib/workflows/types";

import { CATEGORY_ORDER, DRAG_MIME, type DragPayload, NODE_ICONS } from "../node-meta";

interface Item {
  key: string;
  payload: DragPayload;
  label: string;
  description: string;
  category: PaletteNodeType["category"];
}

/** Every node type plus the custom functions of nodes.py; drag onto the canvas or press Enter to add. */
export function NodePalette({
  nodeTypes,
  functions,
  hasInput,
  disabled,
  onAdd,
}: {
  nodeTypes: PaletteNodeType[];
  functions: CustomFunction[];
  hasInput: boolean;
  disabled: boolean;
  onAdd: (payload: DragPayload) => void;
}) {
  const t = useTranslations("workflows");
  const [query, setQuery] = React.useState("");

  const items = React.useMemo<Item[]>(() => {
    const base: Item[] = nodeTypes
      .filter((nt) => nt.type !== "custom" && !(nt.type === "input" && hasInput))
      .map((nt) => ({
        key: nt.type,
        payload: { type: nt.type },
        label: t(`nodeTypes.${nt.type}.label`),
        description: t(`nodeTypes.${nt.type}.description`),
        category: nt.category,
      }));
    const custom: Item[] = functions.map((fn) => ({
      key: `custom:${fn.name}`,
      payload: { type: "custom" as NodeType, fn: fn.name },
      label: fn.name,
      description: fn.description || t("nodeTypes.custom.description"),
      category: "custom",
    }));
    const q = query.trim().toLowerCase();
    return [...base, ...custom].filter(
      (i) => !q || i.label.toLowerCase().includes(q) || i.description.toLowerCase().includes(q) || i.key.includes(q),
    );
  }, [nodeTypes, functions, hasInput, query, t]);

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-bg" aria-label={t("canvas.palette")}>
      <div className="border-b border-border p-2">
        <label className="relative block">
          <span className="sr-only">{t("canvas.paletteSearch")}</span>
          <Search className="pointer-events-none absolute left-2 top-2 size-4 text-fg-subtle" aria-hidden />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("canvas.paletteSearch")}
            className="h-8 pl-7"
          />
        </label>
        <p className="mt-1.5 text-[11px] text-fg-subtle">{t("canvas.dragHint")}</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {items.length === 0 ? <p className="px-1 py-4 text-xs text-fg-subtle">{t("canvas.paletteEmpty")}</p> : null}
        {CATEGORY_ORDER.map((category) => {
          const group = items.filter((i) => i.category === category);
          if (group.length === 0) return null;
          return (
            <div key={category} className="mb-3">
              <p className="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">
                {t(`canvas.categories.${category}`)}
              </p>
              <ul className="space-y-1">
                {group.map((item) => {
                  const Icon = NODE_ICONS[item.payload.type];
                  return (
                    <li key={item.key}>
                      <button
                        type="button"
                        draggable={!disabled}
                        disabled={disabled}
                        onDragStart={(e) => {
                          e.dataTransfer.setData(DRAG_MIME, JSON.stringify(item.payload));
                          e.dataTransfer.effectAllowed = "move";
                        }}
                        onClick={() => onAdd(item.payload)}
                        className={cn(
                          "flex w-full items-start gap-2 rounded-md border border-border bg-surface px-2 py-1.5 text-left transition-colors hover:border-border-strong hover:bg-subtle disabled:cursor-not-allowed disabled:opacity-50",
                          !disabled && "cursor-grab active:cursor-grabbing",
                        )}
                        title={item.description}
                      >
                        <Icon className="mt-0.5 size-3.5 shrink-0 text-fg-muted" aria-hidden />
                        <span className="min-w-0">
                          <span className={cn("block truncate text-xs font-medium", item.category === "custom" && "font-mono")}>
                            {item.label}
                          </span>
                          <span className="line-clamp-2 text-[11px] leading-4 text-fg-subtle">{item.description}</span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
    </aside>
  );
}

"use client";

import { useTranslations } from "next-intl";

import { COMPONENT_TYPES, type ComponentType } from "../types";
import { DRAG_TYPE } from "./canvas";
import { TypeIcon } from "./type-icon";

/** Component palette: click to add at the first free spot, or drag onto the canvas. */
export function Palette({ onAdd, disabled }: { onAdd: (type: ComponentType) => void; disabled?: boolean }) {
  const t = useTranslations("interfaces");
  return (
    <div className="flex flex-col gap-1" role="list" aria-label={t("editor.palette")}>
      <p className="px-1 pb-1 text-xs font-medium uppercase tracking-wide text-fg-subtle">{t("editor.palette")}</p>
      {COMPONENT_TYPES.map((type) => (
        <button
          key={type}
          type="button"
          role="listitem"
          draggable={!disabled}
          disabled={disabled}
          onDragStart={(e) => {
            e.dataTransfer.setData(DRAG_TYPE, type);
            e.dataTransfer.effectAllowed = "copy";
          }}
          onClick={() => onAdd(type)}
          className="flex items-start gap-2 rounded-md border border-transparent px-2 py-1.5 text-left hover:border-border hover:bg-subtle disabled:opacity-50"
          title={t(`types.${type}.description`)}
        >
          <TypeIcon type={type} className="mt-0.5 size-4 shrink-0 text-fg-muted" />
          <span className="min-w-0">
            <span className="block text-sm font-medium text-fg">{t(`types.${type}.name`)}</span>
            <span className="block truncate text-xs text-fg-subtle">{t(`types.${type}.short`)}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

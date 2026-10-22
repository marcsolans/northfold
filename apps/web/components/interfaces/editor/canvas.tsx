"use client";

import { cn } from "@messer/ui";
import { AlertTriangle, GripVertical } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import type { ComponentDef, ComponentType, Grid } from "../types";
import { GRID_COLUMNS, clampGrid, resolveCollisions } from "./model";
import { TypeIcon } from "./type-icon";

export const DRAG_TYPE = "application/x-messer-component";
const GAP = 12;

interface DragState {
  id: string;
  mode: "move" | "resize";
  startX: number;
  startY: number;
  origin: Grid;
  current: Grid;
  moved: boolean;
}

/**
 * Design canvas: a 12-column grid where components are moved (drag the tile or use the arrow keys) and resized
 * (drag the corner or Shift + arrows). Overlapping components are pushed down. Palette items can be dropped in.
 */
export function GridCanvas({
  components,
  selectedId,
  rowHeight,
  issues,
  onSelect,
  onChange,
  onDropNew,
  onDelete,
  renderTile,
}: {
  components: ComponentDef[];
  selectedId: string | null;
  rowHeight: number;
  issues: Record<string, number>;
  onSelect: (id: string | null) => void;
  onChange: (components: ComponentDef[], movedId: string) => void;
  onDropNew: (type: ComponentType, at: { x: number; y: number }) => void;
  onDelete: (id: string) => void;
  renderTile: (comp: ComponentDef) => React.ReactNode;
}) {
  const t = useTranslations("interfaces.editor");
  const ref = React.useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = React.useState(960);
  const [drag, setDrag] = React.useState<DragState | null>(null);
  const [dropHint, setDropHint] = React.useState<{ x: number; y: number } | null>(null);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const colW = Math.max(16, (width - GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS);
  const box = (g: Grid): React.CSSProperties => ({
    left: g.x * (colW + GAP),
    top: g.y * (rowHeight + GAP),
    width: g.w * colW + (g.w - 1) * GAP,
    height: g.h * rowHeight + (g.h - 1) * GAP,
  });
  const gridOf = (comp: ComponentDef) => (drag && drag.id === comp.id ? drag.current : comp.grid);
  const bottom = components.reduce((max, c) => Math.max(max, gridOf(c).y + gridOf(c).h), 0);
  const rows = Math.max(bottom + 4, 10);

  const commit = (id: string, grid: Grid) => {
    const next = components.map((c) => (c.id === id ? { ...c, grid } : c));
    onChange(resolveCollisions(next, id), id);
  };

  const onPointerDown = (e: React.PointerEvent, comp: ComponentDef, mode: DragState["mode"]) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setDrag({ id: comp.id, mode, startX: e.clientX, startY: e.clientY, origin: comp.grid, current: comp.grid, moved: false });
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag) return;
    const dx = Math.round((e.clientX - drag.startX) / (colW + GAP));
    const dy = Math.round((e.clientY - drag.startY) / (rowHeight + GAP));
    const o = drag.origin;
    const current =
      drag.mode === "move"
        ? clampGrid({ ...o, x: o.x + dx, y: o.y + dy })
        : clampGrid({ ...o, w: Math.min(o.w + dx, GRID_COLUMNS - o.x), h: o.h + dy });
    const moved = drag.moved || Math.abs(e.clientX - drag.startX) > 3 || Math.abs(e.clientY - drag.startY) > 3;
    if (moved !== drag.moved || JSON.stringify(current) !== JSON.stringify(drag.current)) setDrag({ ...drag, current, moved });
  };

  const onPointerUp = () => {
    if (!drag) return;
    if (drag.moved && JSON.stringify(drag.current) !== JSON.stringify(drag.origin)) commit(drag.id, drag.current);
    else onSelect(drag.id);
    setDrag(null);
  };

  const onKeyDown = (e: React.KeyboardEvent, comp: ComponentDef) => {
    const step: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const delta = step[e.key];
    if (delta) {
      e.preventDefault();
      const g = comp.grid;
      const grid = e.shiftKey
        ? clampGrid({ ...g, w: Math.min(g.w + delta[0], GRID_COLUMNS - g.x), h: g.h + delta[1] })
        : clampGrid({ ...g, x: g.x + delta[0], y: g.y + delta[1] });
      onSelect(comp.id);
      commit(comp.id, grid);
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      onDelete(comp.id);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(comp.id);
    }
  };

  const cellAt = (clientX: number, clientY: number) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return {
      x: Math.min(GRID_COLUMNS - 1, Math.max(0, Math.floor((clientX - rect.left) / (colW + GAP)))),
      y: Math.max(0, Math.floor((clientY - rect.top) / (rowHeight + GAP))),
    };
  };

  return (
    <div
      ref={ref}
      className="relative w-full select-none"
      style={{ height: rows * (rowHeight + GAP) }}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => setDrag(null)}
      onClick={(e) => {
        if (e.target === e.currentTarget) onSelect(null);
      }}
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes(DRAG_TYPE)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        setDropHint(cellAt(e.clientX, e.clientY));
      }}
      onDragLeave={() => setDropHint(null)}
      onDrop={(e) => {
        const type = e.dataTransfer.getData(DRAG_TYPE) as ComponentType;
        setDropHint(null);
        if (!type) return;
        e.preventDefault();
        onDropNew(type, cellAt(e.clientX, e.clientY));
      }}
      role="application"
      aria-label={t("canvasLabel")}
    >
      <div aria-hidden className="pointer-events-none absolute inset-0 flex gap-3">
        {Array.from({ length: GRID_COLUMNS }, (_, i) => (
          <div key={i} className="h-full flex-1 rounded-sm bg-subtle/70" />
        ))}
      </div>
      {dropHint ? (
        <div
          aria-hidden
          className="pointer-events-none absolute rounded-md border-2 border-dashed border-accent/60 bg-accent-soft/40"
          style={box({ x: Math.min(dropHint.x, GRID_COLUMNS - 3), y: dropHint.y, w: 3, h: 2 })}
        />
      ) : null}
      {components.map((comp) => {
        const g = gridOf(comp);
        const selected = comp.id === selectedId;
        const dragging = drag?.id === comp.id && drag.moved;
        const count = issues[comp.id] ?? 0;
        return (
          <div
            key={comp.id}
            role="button"
            tabIndex={0}
            aria-pressed={selected}
            aria-label={t("tileLabel", { title: comp.title || comp.id, x: comp.grid.x, y: comp.grid.y, w: comp.grid.w, h: comp.grid.h })}
            onPointerDown={(e) => onPointerDown(e, comp, "move")}
            onKeyDown={(e) => onKeyDown(e, comp)}
            className={cn(
              "group absolute flex cursor-grab flex-col overflow-hidden rounded-md border bg-surface shadow-sm outline-none transition-[box-shadow] focus-visible:ring-2 focus-visible:ring-ring/40",
              selected ? "border-accent ring-1 ring-accent" : "border-border hover:border-border-strong",
              dragging && "z-10 cursor-grabbing opacity-90 shadow-lg",
              count > 0 && !selected && "border-danger/60",
            )}
            style={box(g)}
          >
            <div className="flex h-7 shrink-0 items-center gap-1.5 border-b border-border bg-subtle px-2 text-xs text-fg-muted">
              <GripVertical className="size-3.5 text-fg-subtle" aria-hidden />
              <TypeIcon type={comp.type} className="size-3.5" />
              <span className="min-w-0 truncate font-medium text-fg">{comp.title || comp.id}</span>
              {count > 0 ? (
                <span className="ml-auto inline-flex items-center gap-0.5 text-danger" title={t("tileIssues", { count })}>
                  <AlertTriangle className="size-3.5" aria-hidden />
                  {count}
                </span>
              ) : null}
            </div>
            <div className="pointer-events-none min-h-0 flex-1 overflow-hidden" aria-hidden>
              {renderTile(comp)}
            </div>
            <div
              role="presentation"
              onPointerDown={(e) => onPointerDown(e, comp, "resize")}
              className="absolute bottom-0 right-0 size-4 cursor-se-resize opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
              style={{ background: "linear-gradient(135deg, transparent 50%, var(--border-strong) 50%)" }}
              title={t("resize")}
            />
          </div>
        );
      })}
    </div>
  );
}

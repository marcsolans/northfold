"use client";

import { Tabs, TabsList, TabsTrigger, cn } from "@messer/ui";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useDataLabels } from "../labels";
import type { InterfaceSource } from "../source";
import type { ComponentDef, InterfaceDefinition, ScreenDef } from "../types";
import { ComponentView } from "./component-view";

export function sortedComponents(screen: ScreenDef): ComponentDef[] {
  return [...screen.components].sort((a, b) => a.grid.y - b.grid.y || a.grid.x - b.grid.x);
}

/** Grid item style: explicit 12-column placement from md up; stacked (by y, x) on phones. */
export function gridItemStyle(comp: ComponentDef): React.CSSProperties {
  return {
    "--gc": `${comp.grid.x + 1} / span ${comp.grid.w}`,
    "--gr": `${comp.grid.y + 1} / span ${comp.grid.h}`,
    "--mh": `calc(var(--row, 56px) * ${Math.max(comp.grid.h, comp.type === "kpi" ? 2 : 4)})`,
  } as React.CSSProperties;
}

export const GRID_CLASS =
  "grid grid-cols-1 gap-3 md:grid-cols-12 md:[grid-auto-rows:var(--row,56px)]";
export const GRID_ITEM_CLASS = "min-h-0 min-w-0 h-[var(--mh)] md:h-auto md:[grid-column:var(--gc)] md:[grid-row:var(--gr)]";

function ScreenGrid({ screen, source, drafts }: { screen: ScreenDef; source: InterfaceSource; drafts?: Record<string, ComponentDef> }) {
  const t = useTranslations("interfaces");
  const labels = useDataLabels();
  if (screen.components.length === 0) {
    return <p className="rounded-md border border-dashed border-border-strong p-8 text-center text-sm text-fg-muted">{t("renderer.emptyScreen")}</p>;
  }
  return (
    <div className={GRID_CLASS}>
      {sortedComponents(screen).map((comp) => (
        <div key={comp.id} className={GRID_ITEM_CLASS} style={gridItemStyle(comp)}>
          <ComponentView comp={comp} source={source} labels={labels} draft={drafts?.[comp.id] ?? null} />
        </div>
      ))}
    </div>
  );
}

/** Renders an interface definition (all its screens) against a data source. */
export function InterfaceRenderer({
  definition,
  source,
  drafts,
  className,
}: {
  definition: InterfaceDefinition;
  source: InterfaceSource;
  /** Components to preview from their unsaved definition (editor). */
  drafts?: Record<string, ComponentDef>;
  className?: string;
}) {
  const t = useTranslations("interfaces");
  const [active, setActive] = React.useState(definition.screens[0]?.id ?? "");
  const screen = definition.screens.find((s) => s.id === active) ?? definition.screens[0];
  if (!screen) return null;
  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {definition.screens.length > 1 ? (
        <Tabs value={screen.id} onValueChange={setActive}>
          <TabsList aria-label={t("renderer.screens")}>
            {definition.screens.map((s) => (
              <TabsTrigger key={s.id} value={s.id}>
                {s.title}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      ) : null}
      <ScreenGrid key={screen.id} screen={screen} source={source} drafts={drafts} />
    </div>
  );
}

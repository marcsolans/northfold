"use client";

import { Alert, Button, Checkbox, Field, Input } from "@messer/ui";
import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import type { Role } from "@/lib/types";

import type { Binding, ComponentDef, FormFieldDef, InterfaceDefinition, Issue } from "../types";
import { type BindingContext, BindingEditor } from "./binding-editor";
import { Group, NumberField, SelectField, SwitchField, TextField } from "./fields";
import { GRID_COLUMNS, clampGrid } from "./model";
import { PropsForm } from "./props-forms";
import { TypeIcon } from "./type-icon";

const ID_RE = /^[a-z][a-z0-9_-]{0,63}$/;
const ROLES: Role[] = ["viewer", "builder", "admin", "owner"];

function IssuesList({ issues }: { issues: Issue[] }) {
  if (issues.length === 0) return null;
  return (
    <div className="px-3 pt-3">
      <Alert tone="danger">
        <ul className="flex flex-col gap-1 text-xs">
          {issues.map((i, n) => (
            <li key={`${i.path}-${n}`}>
              <span className="font-mono">{i.path.replace(/^screens\[\d+\]\.components\[\d+\]\.?/, "") || "·"}</span> — {i.message}
            </li>
          ))}
        </ul>
      </Alert>
    </div>
  );
}

/** Properties of the selected component: identity, layout, type-specific props and binding. */
export function ComponentProperties({
  comp,
  ctx,
  issues,
  idTaken,
  onChange,
  onRename,
  onDelete,
}: {
  comp: ComponentDef;
  ctx: BindingContext;
  issues: Issue[];
  idTaken: (id: string) => boolean;
  onChange: (comp: ComponentDef) => void;
  onRename: (id: string) => void;
  onDelete: () => void;
}) {
  const t = useTranslations("interfaces");
  const [idDraft, setIdDraft] = React.useState(comp.id);
  React.useEffect(() => setIdDraft(comp.id), [comp.id]);
  const idError = !ID_RE.test(idDraft) ? t("editor.idInvalid") : idDraft !== comp.id && idTaken(idDraft) ? t("editor.idTaken") : null;
  const setGrid = (patch: Partial<ComponentDef["grid"]>) => onChange({ ...comp, grid: clampGrid({ ...comp.grid, ...patch }) });
  const formFields = comp.type === "form" && Array.isArray(comp.props.fields) ? (comp.props.fields as FormFieldDef[]).map((f) => f.name) : undefined;
  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <TypeIcon type={comp.type} className="size-4 text-fg-muted" />
        <p className="min-w-0 flex-1 truncate text-sm font-semibold text-fg">{t(`types.${comp.type}.name`)}</p>
        <Button size="icon-sm" variant="ghost" aria-label={t("editor.deleteComponent")} title={t("editor.deleteComponent")} onClick={onDelete}>
          <Trash2 />
        </Button>
      </div>
      <IssuesList issues={issues} />
      <Group title={t("editor.general")}>
        <Field label={t("editor.componentId")} hint={t("editor.componentIdHint")} error={idError ?? undefined}>
          <Input
            value={idDraft}
            aria-invalid={idError ? true : undefined}
            onChange={(e) => setIdDraft(e.target.value)}
            onBlur={() => {
              if (!idError && idDraft !== comp.id) onRename(idDraft);
            }}
            className="font-mono text-xs"
          />
        </Field>
        <TextField label={t("editor.title")} value={comp.title ?? ""} onChange={(title) => onChange({ ...comp, title: title || null })} />
        <TextField label={t("editor.description")} value={comp.description ?? ""} onChange={(d) => onChange({ ...comp, description: d || null })} />
      </Group>
      <Group title={t("editor.layout")}>
        <div className="grid grid-cols-4 gap-2">
          <NumberField label="x" value={comp.grid.x} min={0} max={GRID_COLUMNS - 1} onChange={(v) => setGrid({ x: v ?? 0 })} />
          <NumberField label="y" value={comp.grid.y} min={0} onChange={(v) => setGrid({ y: v ?? 0 })} />
          <NumberField label="w" value={comp.grid.w} min={1} max={GRID_COLUMNS} onChange={(v) => setGrid({ w: v ?? 1 })} />
          <NumberField label="h" value={comp.grid.h} min={1} max={40} onChange={(v) => setGrid({ h: v ?? 1 })} />
        </div>
        <p className="text-xs text-fg-subtle">{t("editor.layoutHint")}</p>
      </Group>
      <PropsForm comp={comp} ctx={{ ...ctx, formFields }} onChange={(props) => onChange({ ...comp, props })} />
      <Group title={t("editor.binding")}>
        <BindingEditor
          type={comp.type}
          binding={(comp.binding ?? null) as Binding | null}
          ctx={{ ...ctx, formFields }}
          onChange={(binding) => onChange({ ...comp, binding })}
        />
      </Group>
    </div>
  );
}

/** Interface-level settings shown when nothing is selected: identity, theme, access and screens. */
export function InterfaceSettings({
  definition,
  issues,
  onChange,
  onAddScreen,
  onDeleteScreen,
  activeScreen,
}: {
  definition: InterfaceDefinition;
  issues: Issue[];
  onChange: (definition: InterfaceDefinition) => void;
  onAddScreen: () => void;
  onDeleteScreen: (id: string) => void;
  activeScreen: string;
}) {
  const t = useTranslations("interfaces.settings");
  const theme = definition.theme ?? {};
  const auth = definition.auth ?? {};
  const required = auth.required ?? definition.kind === "app";
  const roles = auth.roles ?? [];
  const screen = definition.screens.find((s) => s.id === activeScreen);
  return (
    <div className="flex flex-col">
      <IssuesList issues={issues} />
      <Group title={t("identity")}>
        <TextField label={t("name")} value={definition.name} onChange={(name) => onChange({ ...definition, name })} />
        <TextField label={t("slug")} hint={t("slugHint")} value={definition.slug} onChange={(slug) => onChange({ ...definition, slug })} mono />
        <TextField label={t("description")} value={definition.description ?? ""} onChange={(description) => onChange({ ...definition, description })} />
      </Group>
      <Group title={t("theme")}>
        <Field label={t("accent")} hint={t("accentHint")}>
          <div className="flex items-center gap-2">
            <input
              type="color"
              aria-label={t("accent")}
              value={theme.accent ?? "#D52B1E"}
              onChange={(e) => onChange({ ...definition, theme: { ...theme, accent: e.target.value.toUpperCase() } })}
              className="h-8 w-10 cursor-pointer rounded-md border border-border bg-surface"
            />
            <Input
              aria-label={t("accentHex")}
              value={theme.accent ?? "#D52B1E"}
              onChange={(e) => onChange({ ...definition, theme: { ...theme, accent: e.target.value } })}
              className="font-mono text-xs"
            />
          </div>
        </Field>
        <SelectField
          label={t("mode")}
          value={theme.mode ?? "system"}
          options={(["system", "light", "dark"] as const).map((m) => ({ value: m, label: t(`modes.${m}`) }))}
          onChange={(mode) => onChange({ ...definition, theme: { ...theme, mode } })}
        />
        <SelectField
          label={t("density")}
          value={theme.density ?? "comfortable"}
          options={(["comfortable", "compact"] as const).map((d) => ({ value: d, label: t(`densities.${d}`) }))}
          onChange={(density) => onChange({ ...definition, theme: { ...theme, density } })}
        />
        <TextField
          label={t("logo")}
          hint={t("logoHint")}
          value={theme.logo_url ?? ""}
          onChange={(logo_url) => onChange({ ...definition, theme: { ...theme, logo_url: logo_url || null } })}
        />
      </Group>
      <Group title={t("access")}>
        <SwitchField
          label={t("loginRequired")}
          hint={definition.kind === "chat" ? t("loginRequiredChatHint") : t("loginRequiredHint")}
          checked={required}
          onChange={(v) => onChange({ ...definition, auth: { required: v, roles: v ? roles : [] } })}
        />
        {required ? (
          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1 text-sm text-fg">{t("roles")}</legend>
            <p className="text-xs text-fg-subtle">{t("rolesHint")}</p>
            {ROLES.map((role) => (
              <label key={role} className="flex items-center gap-2 text-sm text-fg">
                <Checkbox
                  checked={roles.includes(role)}
                  onCheckedChange={(c) =>
                    onChange({
                      ...definition,
                      auth: { required: true, roles: c === true ? [...roles, role] : roles.filter((r) => r !== role) },
                    })
                  }
                />
                {t(`roleNames.${role}`)}
              </label>
            ))}
          </fieldset>
        ) : null}
      </Group>
      {definition.kind === "app" ? (
        <Group
          title={t("screens")}
          actions={
            <Button size="sm" variant="ghost" onClick={onAddScreen}>
              <Plus />
              {t("addScreen")}
            </Button>
          }
        >
          {screen ? (
            <>
              <TextField
                label={t("screenTitle")}
                value={screen.title}
                onChange={(title) =>
                  onChange({ ...definition, screens: definition.screens.map((s) => (s.id === screen.id ? { ...s, title } : s)) })
                }
              />
              <Button size="sm" variant="danger" disabled={definition.screens.length <= 1} onClick={() => onDeleteScreen(screen.id)}>
                <Trash2 />
                {t("deleteScreen")}
              </Button>
            </>
          ) : null}
        </Group>
      ) : null}
    </div>
  );
}

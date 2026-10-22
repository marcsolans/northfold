"use client";

import {
  Alert,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
  Field,
  Input,
  Textarea,
} from "@messer/ui";
import { Braces, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { isVariableName, variableDiagnostics } from "@/lib/studio/agent-config";
import type { AgentConfig, PromptVariable } from "@/lib/studio/types";

import { Section } from "./fields";

export function PromptSection({
  config,
  onChange,
  readOnly,
  variablesError,
}: {
  config: AgentConfig;
  onChange: (patch: Partial<AgentConfig>) => void;
  readOnly: boolean;
  variablesError: string | null;
}) {
  const t = useTranslations("studio.builder.prompt");
  const ref = React.useRef<HTMLTextAreaElement>(null);
  const diag = variableDiagnostics(config.system_prompt, config.variables);

  const insertVariable = (name: string) => {
    const el = ref.current;
    const token = `{{${name}}}`;
    const prompt = config.system_prompt;
    const start = el?.selectionStart ?? prompt.length;
    const end = el?.selectionEnd ?? prompt.length;
    const next = prompt.slice(0, start) + token + prompt.slice(end);
    const variables = config.variables.some((v) => v.name === name)
      ? config.variables
      : [...config.variables, { name, description: "", default: "" }];
    onChange({ system_prompt: next, variables });
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const setVariable = (index: number, patch: Partial<PromptVariable>) =>
    onChange({ variables: config.variables.map((v, i) => (i === index ? { ...v, ...patch } : v)) });

  const addVariable = () => {
    let n = config.variables.length + 1;
    while (config.variables.some((v) => v.name === `variable_${n}`)) n += 1;
    onChange({ variables: [...config.variables, { name: `variable_${n}`, description: "", default: "" }] });
  };

  return (
    <Section
      id="prompt"
      title={t("title")}
      description={t("description")}
      actions={
        readOnly ? null : (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="secondary">
                <Braces />
                {t("insertVariable")}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent className="w-60">
              <DropdownMenuLabel>{t("insertVariableHint")}</DropdownMenuLabel>
              {config.variables.length === 0 ? (
                <p className="px-2 py-1.5 text-xs text-fg-subtle">{t("noVariables")}</p>
              ) : (
                config.variables
                  .filter((v) => isVariableName(v.name))
                  .map((v) => (
                    <DropdownMenuItem key={v.name} onSelect={() => insertVariable(v.name)}>
                      <span className="font-mono text-xs">{`{{${v.name}}}`}</span>
                    </DropdownMenuItem>
                  ))
              )}
              <DropdownMenuItem onSelect={addVariable}>
                <Plus />
                {t("newVariable")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )
      }
    >
      <Field htmlFor="system-prompt" label={<span className="sr-only">{t("title")}</span>} hint={t("hint")}>
        <Textarea
          id="system-prompt"
          ref={ref}
          value={config.system_prompt}
          readOnly={readOnly}
          rows={12}
          spellCheck
          className="min-h-56 font-mono text-xs leading-relaxed"
          placeholder={t("placeholder")}
          onChange={(e) => onChange({ system_prompt: e.target.value })}
        />
      </Field>
      {diag.undeclared.length > 0 ? (
        <Alert
          tone="warning"
          action={
            readOnly ? null : (
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  onChange({
                    variables: [
                      ...config.variables,
                      ...diag.undeclared.map((name) => ({ name, description: "", default: "" })),
                    ],
                  })
                }
              >
                {t("declare")}
              </Button>
            )
          }
        >
          {t("undeclared", { names: diag.undeclared.map((n) => `{{${n}}}`).join(", ") })}
        </Alert>
      ) : null}

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-medium">{t("variables")}</h3>
          {readOnly ? null : (
            <Button size="sm" variant="ghost" onClick={addVariable}>
              <Plus />
              {t("addVariable")}
            </Button>
          )}
        </div>
        {config.variables.length === 0 ? (
          <p className="text-xs text-fg-subtle">{t("variablesEmpty")}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {config.variables.map((v, i) => {
              const unused = diag.unused.includes(v.name);
              return (
                <li key={i} className="grid grid-cols-1 gap-2 rounded-md border border-border p-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
                  <Input
                    aria-label={t("variableName")}
                    value={v.name}
                    readOnly={readOnly}
                    className="font-mono text-xs"
                    aria-invalid={!isVariableName(v.name) || undefined}
                    onChange={(e) => setVariable(i, { name: e.target.value.replace(/\s/g, "_") })}
                  />
                  <Input
                    aria-label={t("variableDescription")}
                    placeholder={t("variableDescription")}
                    value={v.description}
                    readOnly={readOnly}
                    onChange={(e) => setVariable(i, { description: e.target.value })}
                  />
                  <Input
                    aria-label={t("variableDefault")}
                    placeholder={t("variableDefault")}
                    value={v.default}
                    readOnly={readOnly}
                    onChange={(e) => setVariable(i, { default: e.target.value })}
                  />
                  <div className="flex items-center justify-end gap-1">
                    {unused ? <span className="text-xs text-fg-subtle">{t("unused")}</span> : null}
                    {readOnly ? null : (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={t("removeVariable", { name: v.name })}
                        onClick={() => onChange({ variables: config.variables.filter((_, j) => j !== i) })}
                      >
                        <Trash2 />
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {variablesError ? (
          <p className="mt-2 text-xs text-danger" role="alert">
            {variablesError}
          </p>
        ) : null}
      </div>
    </Section>
  );
}

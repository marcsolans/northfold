"use client";

import { Button, Checkbox, Field, Input, RadioCards, Select, Switch, Textarea } from "@messer/ui";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { defaultGuardrail } from "@/lib/studio/agent-config";
import {
  type AgentConfig,
  COMPACTION_STRATEGIES,
  type CompactionStrategy,
  GUARDRAIL_TYPES,
  type GuardrailConfig,
  type KnowledgeBaseSummary,
  MODEL_TIERS,
  type ModelTier,
} from "@/lib/studio/types";

import { NumberInput, Section, TagInput } from "./fields";

type Patch = (patch: Partial<AgentConfig>) => void;

export function GeneralSection({ config, onChange, readOnly }: { config: AgentConfig; onChange: Patch; readOnly: boolean }) {
  const t = useTranslations("studio.builder.general");
  return (
    <Section id="general" title={t("title")}>
      <Field label={t("description")} htmlFor="agent-description-field" hint={t("descriptionHint")}>
        <Textarea
          id="agent-description-field"
          value={config.description}
          readOnly={readOnly}
          rows={2}
          maxLength={2000}
          onChange={(e) => onChange({ description: e.target.value })}
        />
      </Field>
    </Section>
  );
}

export function ModelSection({
  config,
  onChange,
  readOnly,
  errors,
}: {
  config: AgentConfig;
  onChange: Patch;
  readOnly: boolean;
  errors: Partial<Record<"model" | "temperature" | "max_tokens" | "max_iter" | "timeout", string>>;
}) {
  const t = useTranslations("studio.builder.model");
  const tt = useTranslations("studio.tiers");
  const [advanced, setAdvanced] = React.useState(Boolean(config.model));
  return (
    <Section id="model" title={t("title")} description={t("description")}>
      <fieldset disabled={readOnly}>
        <legend className="sr-only">{t("tier")}</legend>
        <RadioCards
          value={config.model ? "" : (config.model_tier ?? "standard")}
          onValueChange={(v) => onChange({ model_tier: v as ModelTier, model: null })}
          className="grid-cols-1 sm:grid-cols-3"
          options={MODEL_TIERS.map((value) => ({
            value,
            label: tt(`${value}.label`),
            description: tt(`${value}.description`),
            disabled: readOnly,
          }))}
        />
      </fieldset>
      <div>
        <button
          type="button"
          className="flex items-center gap-1 text-xs font-medium text-fg-muted hover:text-fg"
          aria-expanded={advanced}
          aria-controls="model-advanced"
          onClick={() => setAdvanced((a) => !a)}
        >
          <ChevronDown className={advanced ? "size-3.5 rotate-180 transition-transform" : "size-3.5 transition-transform"} />
          {t("advanced")}
        </button>
        {advanced ? (
          <div id="model-advanced" className="mt-2">
            <Field label={t("explicit")} htmlFor="explicit-model" hint={config.model ? t("explicitActive") : t("explicitHint")} error={errors.model}>
              <div className="flex gap-2">
                <Input
                  id="explicit-model"
                  value={config.model ?? ""}
                  readOnly={readOnly}
                  spellCheck={false}
                  className="font-mono text-xs"
                  placeholder={t("explicitPlaceholder")}
                  aria-invalid={Boolean(errors.model) || undefined}
                  onChange={(e) => onChange({ model: e.target.value.trim() || null })}
                />
                {config.model && !readOnly ? (
                  <Button size="md" variant="ghost" onClick={() => onChange({ model: null })}>
                    {t("useTier")}
                  </Button>
                ) : null}
              </div>
            </Field>
          </div>
        ) : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("temperature")} htmlFor="temperature" hint={t("temperatureHint")} error={errors.temperature}>
          <NumberInput
            id="temperature"
            value={config.temperature}
            nullable
            integer={false}
            disabled={readOnly}
            placeholder={t("default")}
            invalid={Boolean(errors.temperature)}
            onChange={(v) => onChange({ temperature: v })}
          />
        </Field>
        <Field label={t("maxTokens")} htmlFor="max-tokens" error={errors.max_tokens}>
          <NumberInput
            id="max-tokens"
            value={config.max_tokens}
            disabled={readOnly}
            invalid={Boolean(errors.max_tokens)}
            onChange={(v) => onChange({ max_tokens: v ?? 4096 })}
          />
        </Field>
        <Field label={t("maxIter")} htmlFor="max-iter" hint={t("maxIterHint")} error={errors.max_iter}>
          <NumberInput
            id="max-iter"
            value={config.max_iter}
            disabled={readOnly}
            invalid={Boolean(errors.max_iter)}
            onChange={(v) => onChange({ max_iter: v ?? 10 })}
          />
        </Field>
        <Field label={t("timeout")} htmlFor="timeout" hint={t("timeoutHint")} error={errors.timeout}>
          <NumberInput
            id="timeout"
            value={config.timeout}
            nullable
            disabled={readOnly}
            placeholder={t("noLimit")}
            invalid={Boolean(errors.timeout)}
            onChange={(v) => onChange({ timeout: v })}
          />
        </Field>
      </div>
    </Section>
  );
}

export function KnowledgeSection({
  config,
  onChange,
  readOnly,
  knowledgeBases,
}: {
  config: AgentConfig;
  onChange: Patch;
  readOnly: boolean;
  knowledgeBases: KnowledgeBaseSummary[];
}) {
  const t = useTranslations("studio.builder.knowledge");
  const selected = new Set(config.knowledge_bases);
  const missing = config.knowledge_bases.filter((id) => !knowledgeBases.some((kb) => kb.id === id));
  const toggle = (id: string, on: boolean) =>
    onChange({ knowledge_bases: on ? [...config.knowledge_bases, id] : config.knowledge_bases.filter((x) => x !== id) });
  return (
    <Section id="knowledge" title={t("title")} description={t("description")}>
      {knowledgeBases.length === 0 && missing.length === 0 ? (
        <p className="text-sm text-fg-subtle">{t("empty")}</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {knowledgeBases.map((kb) => (
            <li key={kb.id}>
              <label className="flex items-start gap-2.5 rounded-md border border-border px-3 py-2 text-sm hover:bg-subtle">
                <Checkbox
                  className="mt-0.5"
                  checked={selected.has(kb.id)}
                  disabled={readOnly}
                  onCheckedChange={(c) => toggle(kb.id, c === true)}
                />
                <span className="min-w-0">
                  <span className="block font-medium">{kb.name}</span>
                  {kb.description ? <span className="block truncate text-xs text-fg-muted">{kb.description}</span> : null}
                </span>
              </label>
            </li>
          ))}
          {missing.map((id) => (
            <li key={id} className="flex items-center justify-between rounded-md border border-dashed border-border px-3 py-2 text-xs text-fg-subtle">
              <span className="font-mono">{t("missing", { id })}</span>
              {readOnly ? null : (
                <Button size="sm" variant="ghost" onClick={() => toggle(id, false)}>
                  {t("unlink")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {config.knowledge_bases.length > 0 && !config.tools.some((tool) => tool.type === "builtin" && tool.key === "knowledge_search") ? (
        <p className="text-xs text-warning">{t("needsTool")}</p>
      ) : null}
    </Section>
  );
}

function GuardrailRow({
  type,
  value,
  readOnly,
  error,
  onChange,
}: {
  type: GuardrailConfig["type"];
  value: GuardrailConfig | null;
  readOnly: boolean;
  error: string | null;
  onChange: (value: GuardrailConfig | null) => void;
}) {
  const t = useTranslations("studio.builder.guardrails");
  const id = `guard-${type}`;
  return (
    <li className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <label htmlFor={id} className="flex min-w-0 flex-1 items-start gap-2.5">
          <Switch
            id={id}
            className="mt-0.5"
            checked={value !== null}
            disabled={readOnly}
            onCheckedChange={(on) => onChange(on ? defaultGuardrail(type) : null)}
          />
          <span className="min-w-0">
            <span className="block text-sm font-medium">{t(`types.${type}.label`)}</span>
            <span className="block text-xs text-fg-muted">{t(`types.${type}.description`)}</span>
          </span>
        </label>
        {value ? (
          <div className="w-44">
            <Select
              aria-label={t("mode")}
              value={value.mode}
              disabled={readOnly}
              onValueChange={(mode) => onChange({ ...value, mode: mode as GuardrailConfig["mode"] })}
              options={[
                { value: "enforce", label: t("modes.enforce"), description: t("modes.enforceHint") },
                { value: "shadow", label: t("modes.shadow"), description: t("modes.shadowHint") },
              ]}
            />
          </div>
        ) : null}
      </div>
      {value && type === "topics" ? (
        <Field label={t("topics")} htmlFor={`${id}-topics`} hint={t("topicsHint")} className="mt-3">
          <TagInput
            id={`${id}-topics`}
            values={value.topics}
            disabled={readOnly}
            placeholder={t("topicsPlaceholder")}
            removeLabel={(topic) => t("removeTopic", { topic })}
            onChange={(topics) => onChange({ ...value, topics })}
          />
        </Field>
      ) : null}
      {value && type === "judge" ? (
        <Field label={t("rubric")} htmlFor={`${id}-rubric`} hint={t("rubricHint")} className="mt-3">
          <Textarea
            id={`${id}-rubric`}
            value={value.rubric}
            readOnly={readOnly}
            rows={3}
            placeholder={t("rubricPlaceholder")}
            onChange={(e) => onChange({ ...value, rubric: e.target.value })}
          />
        </Field>
      ) : null}
      {error ? (
        <p className="mt-2 text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </li>
  );
}

export function GuardrailsSection({
  config,
  onChange,
  readOnly,
  errors,
}: {
  config: AgentConfig;
  onChange: Patch;
  readOnly: boolean;
  errors: Record<number, string>;
}) {
  const t = useTranslations("studio.builder.guardrails");
  return (
    <Section id="guardrails" title={t("title")} description={t("description")}>
      <ul className="flex flex-col gap-2">
        {GUARDRAIL_TYPES.map((type) => {
          const index = config.guardrails.findIndex((g) => g.type === type);
          const value = index === -1 ? null : (config.guardrails[index] ?? null);
          return (
            <GuardrailRow
              key={type}
              type={type}
              value={value}
              readOnly={readOnly}
              error={index === -1 ? null : (errors[index] ?? null)}
              onChange={(next) => {
                const others = config.guardrails.filter((g) => g.type !== type);
                if (next === null) onChange({ guardrails: others });
                else if (index === -1) onChange({ guardrails: [...config.guardrails, next] });
                else onChange({ guardrails: config.guardrails.map((g, i) => (i === index ? next : g)) });
              }}
            />
          );
        })}
      </ul>
    </Section>
  );
}

export function MemorySection({
  config,
  onChange,
  readOnly,
  keepLastNError,
}: {
  config: AgentConfig;
  onChange: Patch;
  readOnly: boolean;
  keepLastNError: string | null;
}) {
  const t = useTranslations("studio.builder.memory");
  const memory = config.memory;
  const set = (patch: Partial<AgentConfig["memory"]>) => onChange({ memory: { ...memory, ...patch } });
  return (
    <Section id="memory" title={t("title")} description={t("description")}>
      <label htmlFor="memory-enabled" className="flex items-center gap-2.5 text-sm">
        <Switch id="memory-enabled" checked={memory.enabled} disabled={readOnly} onCheckedChange={(enabled) => set({ enabled })} />
        {t("enabled")}
      </label>
      {memory.enabled ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("compaction")} htmlFor="memory-compaction">
            <Select
              id="memory-compaction"
              aria-label={t("compaction")}
              value={memory.compaction}
              disabled={readOnly}
              onValueChange={(v) => set({ compaction: v as CompactionStrategy })}
              options={COMPACTION_STRATEGIES.map((value) => ({
                value,
                label: t(`strategies.${value}.label`),
                description: t(`strategies.${value}.description`),
              }))}
            />
          </Field>
          {memory.compaction === "last_turns" ? (
            <Field label={t("keepLastN")} htmlFor="memory-keep" error={keepLastNError}>
              <NumberInput
                id="memory-keep"
                value={memory.keep_last_n}
                disabled={readOnly}
                invalid={Boolean(keepLastNError)}
                onChange={(v) => set({ keep_last_n: v ?? 20 })}
              />
            </Field>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-fg-subtle">{t("disabledHint")}</p>
      )}
    </Section>
  );
}

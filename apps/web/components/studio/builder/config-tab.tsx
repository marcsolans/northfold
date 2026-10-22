"use client";

import { Alert, Button } from "@messer/ui";
import { useTranslations } from "next-intl";

import { VoiceSettingsSection } from "@/components/voice";
import type { ConfigErrorCode, ConfigErrorKey } from "@/lib/studio/agent-config";
import { useKnowledgeBasesOptional } from "@/lib/studio/hooks";
import type { AgentConfig, ContextFile } from "@/lib/studio/types";

import { GeneralSection, GuardrailsSection, KnowledgeSection, MemorySection, ModelSection } from "./config-sections";
import { ContextFilesSection } from "./context-files-section";
import { Section } from "./fields";
import { PromptSection } from "./prompt-section";
import { ToolsSection } from "./tools-section";

export type ConfigErrors = Partial<Record<ConfigErrorKey, ConfigErrorCode>>;

export function ConfigTab({
  projectId,
  member,
  config,
  serverContextFiles,
  onChange,
  readOnly,
  readOnlyReason,
  codeMode,
  errors,
  onOpenCode,
}: {
  projectId: string;
  member: string;
  config: AgentConfig;
  serverContextFiles: ContextFile[];
  onChange: (patch: Partial<AgentConfig>) => void;
  readOnly: boolean;
  readOnlyReason: "viewer" | "code_mode" | "code_dirty" | null;
  codeMode: boolean;
  errors: ConfigErrors;
  onOpenCode: () => void;
}) {
  const t = useTranslations("studio.builder");
  const te = useTranslations("studio.builder.errors");
  const kbs = useKnowledgeBasesOptional();
  const err = (key: ConfigErrorKey) => (errors[key] ? te(errors[key]) : undefined);
  const indexed = (prefix: "guardrail" | "mcp") => {
    const out: Record<number, string> = {};
    for (const [key, code] of Object.entries(errors)) {
      const [p, idx] = key.split(".");
      if (p === prefix && code) out[Number(idx)] = te(code);
    }
    return out;
  };

  return (
    <div>
      {readOnlyReason === "code_mode" ? (
        <div className="px-4 pt-4 md:px-5">
          <Alert
            tone="info"
            title={t("codeModeTitle")}
            action={
              <Button size="sm" variant="secondary" onClick={onOpenCode}>
                {t("openCode")}
              </Button>
            }
          >
            {t("codeModeBanner")}
          </Alert>
        </div>
      ) : readOnlyReason === "code_dirty" ? (
        <div className="px-4 pt-4 md:px-5">
          <Alert tone="warning">{t("codeDirtyBanner")}</Alert>
        </div>
      ) : readOnlyReason === "viewer" ? (
        <div className="px-4 pt-4 md:px-5">
          <Alert tone="info">{t("viewerBanner")}</Alert>
        </div>
      ) : null}
      <GeneralSection config={config} onChange={onChange} readOnly={readOnly} />
      <ModelSection
        config={config}
        onChange={onChange}
        readOnly={readOnly}
        errors={{
          model: err("model"),
          temperature: err("temperature"),
          max_tokens: err("max_tokens"),
          max_iter: err("max_iter"),
          timeout: err("timeout"),
        }}
      />
      <PromptSection config={config} onChange={onChange} readOnly={readOnly} variablesError={err("variables") ?? null} />
      <ToolsSection
        projectId={projectId}
        config={config}
        onChange={onChange}
        readOnly={readOnly}
        knowledgeBases={kbs.data ?? null}
        mcpErrors={indexed("mcp")}
      />
      {kbs.data ? <KnowledgeSection config={config} onChange={onChange} readOnly={readOnly} knowledgeBases={kbs.data} /> : null}
      <ContextFilesSection
        projectId={projectId}
        member={member}
        files={serverContextFiles}
        readOnly={readOnlyReason === "viewer" || readOnlyReason === "code_dirty"}
        disabledReason={codeMode ? t("contextFiles.codeMode") : null}
      />
      <GuardrailsSection config={config} onChange={onChange} readOnly={readOnly} errors={indexed("guardrail")} />
      <MemorySection config={config} onChange={onChange} readOnly={readOnly} keepLastNError={err("keep_last_n") ?? null} />
      <Section id="voice" title={t("voice.title")} description={t("voice.description")}>
        <VoiceSettingsSection value={config.voice} onChange={(voice) => onChange({ voice })} disabled={readOnly} />
      </Section>
    </div>
  );
}

"use client";

import { Alert, Button, Field, Select, Skeleton, Switch, Textarea } from "@messer/ui";
import { Volume2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { speechLocale, useVoiceStatus, useVoices } from "./api";
import { speechSynthesisAvailable } from "./speech";
import type { AgentVoiceConfig } from "./types";

const LANGUAGES = ["es", "en", "ca", "eu", "gl", "pt", "fr", "de", "it"] as const;
const DEFAULT_VOICE = "__default__";

function useBrowserVoices(language: string): SpeechSynthesisVoice[] {
  const [voices, setVoices] = React.useState<SpeechSynthesisVoice[]>([]);
  React.useEffect(() => {
    if (!speechSynthesisAvailable()) return;
    const load = () => {
      const prefix = language.slice(0, 2).toLowerCase();
      setVoices(window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith(prefix)));
    };
    load();
    window.speechSynthesis.addEventListener("voiceschanged", load);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", load);
  }, [language]);
  return voices;
}

/**
 * Agent builder → Voice: enable voice, language, voice and opening greeting (``AgentConfig.voice``).
 * Voices come from the TTS provider in use, or from the browser in demo mode (stored as ``provider:voice``).
 */
export function VoiceSettingsSection({
  value,
  onChange,
  disabled = false,
}: {
  value: AgentVoiceConfig;
  onChange: (next: AgentVoiceConfig) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("voice.settings");
  const status = useVoiceStatus();
  const serverVoices = useVoices(value.language || "es", status.data?.mode === "audio");
  const browserVoices = useBrowserVoices(value.language || "es");
  const browserMode = status.data ? status.data.mode === "text" : false;
  const set = (patch: Partial<AgentVoiceConfig>) => onChange({ ...value, ...patch });

  const options = browserMode
    ? browserVoices.map((v) => ({ value: `browser:${v.name}`, label: v.name, description: v.lang }))
    : (serverVoices.data?.items ?? []).map((v) => ({
        value: v.id,
        label: v.name,
        description: [v.language, v.description].filter(Boolean).join(" · ") || undefined,
      }));
  const selected = value.voice && options.some((o) => o.value === value.voice) ? value.voice : DEFAULT_VOICE;

  const preview = () => {
    if (!speechSynthesisAvailable() || !value.greeting.trim()) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(value.greeting);
    utterance.lang = speechLocale(value.language);
    const voice = browserVoices.find((v) => `browser:${v.name}` === value.voice);
    if (voice) utterance.voice = voice;
    window.speechSynthesis.speak(utterance);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium">{t("enabled")}</p>
          <p className="text-xs text-fg-muted">{t("enabledHint")}</p>
        </div>
        <Switch
          checked={value.enabled}
          onCheckedChange={(enabled) => set({ enabled })}
          disabled={disabled}
          aria-label={t("enabled")}
        />
      </div>

      {status.isLoading ? (
        <Skeleton className="h-12 w-full" />
      ) : status.data ? (
        status.data.mode === "audio" ? (
          <Alert tone="success" title={t("audioTitle")}>
            {t("audioBody", { stt: status.data.audio.stt ?? "—", tts: status.data.audio.tts ?? "—" })}
          </Alert>
        ) : (
          <Alert tone="info" title={t("demoTitle")}>
            {t("demoBody")}
          </Alert>
        )
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("language")}>
          <Select
            value={value.language || "es"}
            onValueChange={(language) => set({ language, voice: value.voice.startsWith("browser:") ? "" : value.voice })}
            disabled={disabled}
            options={LANGUAGES.map((code) => ({ value: code, label: t(`languages.${code}`) }))}
          />
        </Field>
        <Field label={t("voice")} hint={browserMode ? t("voiceBrowserHint") : undefined}>
          {serverVoices.isLoading && !browserMode ? (
            <Skeleton className="h-8 w-full" />
          ) : (
            <Select
              value={selected}
              onValueChange={(voice) => set({ voice: voice === DEFAULT_VOICE ? "" : voice })}
              disabled={disabled}
              options={[{ value: DEFAULT_VOICE, label: t("voiceDefault") }, ...options]}
            />
          )}
          {serverVoices.isError ? <p className="mt-1 text-xs text-danger">{t("voicesError")}</p> : null}
        </Field>
      </div>

      <Field label={t("greeting")} hint={t("greetingHint")}>
        <Textarea
          value={value.greeting}
          onChange={(e) => set({ greeting: e.target.value.slice(0, 500) })}
          placeholder={t("greetingPlaceholder")}
          rows={2}
          disabled={disabled}
        />
      </Field>
      {browserMode && value.greeting.trim() && speechSynthesisAvailable() ? (
        <Button size="sm" variant="secondary" onClick={preview}>
          <Volume2 />
          {t("preview")}
        </Button>
      ) : null}
    </div>
  );
}

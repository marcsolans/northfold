"use client";

import { Alert, CodeBlock, CopyButton } from "@messer/ui";
import { useTranslations } from "next-intl";

import type { Channel } from "./types";

const STEP_KEYS = ["1", "2", "3", "4", "5"] as const;

function CopyRow({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  const tc = useTranslations("common");
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-fg-muted">{label}</span>
      <div className="flex items-center gap-2 rounded-md border border-border bg-subtle px-2.5 py-1.5">
        <code className={mono ? "min-w-0 flex-1 truncate font-mono text-xs" : "min-w-0 flex-1 truncate text-sm"} title={value}>
          {value}
        </code>
        <CopyButton value={value} label={tc("copy")} />
      </div>
    </div>
  );
}

/** How to finish the setup with the provider: URLs to paste, the secret (only right after creating or rotating). */
export function SetupPanel({ channel, secret }: { channel: Channel; secret?: string | null }) {
  const t = useTranslations("channels.setup");
  const provider = channel.provider;
  const steps = STEP_KEYS.filter((k) => t.has(`steps.${provider}.${k}`));
  const emailWebhook = secret ? `${channel.webhook_url}?token=${secret}` : null;
  const demoExample =
    channel.demo && secret
      ? `curl -X POST '${channel.webhook_url}?token=${secret}' \\\n  -H 'Content-Type: application/json' \\\n  -d @evento-${provider}.json`
      : null;

  return (
    <div className="flex flex-col gap-4">
      {channel.demo ? (
        <Alert tone="info" title={t("demoTitle")}>
          {t("demoBody")}
        </Alert>
      ) : null}
      {provider === "email" && channel.inbound_address ? (
        <CopyRow label={t("inboundAddress")} value={channel.inbound_address} />
      ) : null}
      <CopyRow label={t(`urlLabel.${provider}`)} value={emailWebhook ?? channel.webhook_url} />
      {secret ? (
        <div className="flex flex-col gap-2">
          <CopyRow label={t(`secretLabel.${channel.demo ? "demo" : provider}`)} value={secret} />
          <p className="text-xs text-warning">{t("secretOnce")}</p>
        </div>
      ) : (
        <p className="text-xs text-fg-muted">{t("secretHidden")}</p>
      )}
      {demoExample ? (
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-fg-muted">{t("demoCurl")}</span>
          <CodeBlock code={demoExample} language="bash" />
        </div>
      ) : null}
      {!channel.demo && steps.length ? (
        <div>
          <p className="mb-1.5 text-sm font-medium">{t("stepsTitle")}</p>
          <ol className="list-decimal space-y-1 pl-5 text-sm text-fg-muted">
            {steps.map((k) => (
              <li key={k}>{t(`steps.${provider}.${k}`)}</li>
            ))}
          </ol>
        </div>
      ) : null}
      {provider === "email" ? <p className="text-xs text-fg-muted">{t("sharedEmail")}</p> : null}
    </div>
  );
}

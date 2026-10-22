"use client";

import { Alert, Button, Card, CardBody, CardHeader, CopyButton, Field, Select, Skeleton, toast } from "@messer/ui";
import { ExternalLink, Radio } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { useRole } from "@/lib/hooks/use-me";
import { errorMessage, useMembers } from "@/lib/studio/hooks";

import { useVoiceStatus } from "./api";
import type { VoiceEnvironment } from "./types";

interface LivekitSession {
  call_id: string;
  conversation_id: string;
  url: string;
  room: string;
  token: string;
  identity: string;
}

/** LiveKit rooms: the agent joins a room and a participant token is issued for any LiveKit client. */
export function LivekitRoomCard({ projectId }: { projectId: string }) {
  const t = useTranslations("voice.livekit");
  const tc = useTranslations("common");
  const status = useVoiceStatus();
  const agents = useMembers(projectId, "agent");
  const canBuild = useRole("builder");
  const [workforce, setWorkforce] = React.useState("");
  const [environment, setEnvironment] = React.useState<VoiceEnvironment>("development");
  const [session, setSession] = React.useState<LivekitSession | null>(null);
  const [creating, setCreating] = React.useState(false);
  const names = (agents.data ?? []).map((m) => m.name);
  const agent = workforce || names[0] || "";

  const create = async () => {
    if (!agent) return;
    setCreating(true);
    try {
      setSession(await http.post<LivekitSession>("/voice/livekit/sessions", { project_id: projectId, workforce: agent, environment }));
    } catch (err) {
      toast.error(errorMessage(err, tc("errorGeneric")));
    } finally {
      setCreating(false);
    }
  };

  const meet = session
    ? `https://meet.livekit.io/custom?${new URLSearchParams({ liveKitUrl: session.url, token: session.token }).toString()}`
    : null;

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <Radio className="size-4 text-fg-subtle" aria-hidden />
            {t("title")}
          </span>
        }
        description={t("description")}
      />
      <CardBody className="space-y-3">
        {status.isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : !status.data?.livekit ? (
          <Alert tone="info" title={t("setupTitle")}>
            {t("setupBody")}
          </Alert>
        ) : !status.data.audio.available ? (
          <Alert tone="warning" title={t("needsAudioTitle")}>
            {t("needsAudioBody")}
          </Alert>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label={t("agent")}>
                <Select value={agent || undefined} onValueChange={setWorkforce} placeholder={tc("loading")} options={names.map((n) => ({ value: n, label: n }))} />
              </Field>
              <Field label={t("environment")}>
                <Select
                  value={environment}
                  onValueChange={(v) => setEnvironment(v as VoiceEnvironment)}
                  options={[
                    { value: "development", label: t("development") },
                    { value: "production", label: t("production") },
                  ]}
                />
              </Field>
              <div className="flex items-end">
                <Button variant="primary" onClick={() => void create()} loading={creating} disabled={!agent || !canBuild}>
                  {t("create")}
                </Button>
              </div>
            </div>
            {session ? (
              <div className="space-y-2 rounded-md border border-border p-3 text-sm">
                <p className="font-medium">{t("ready", { room: session.room })}</p>
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded-sm bg-subtle px-2 py-1 text-xs">{session.url}</code>
                  <CopyButton value={session.url} label={tc("copy")} />
                </div>
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded-sm bg-subtle px-2 py-1 text-xs">{session.token}</code>
                  <CopyButton value={session.token} label={tc("copy")} />
                </div>
                {meet ? (
                  <Button asChild size="sm" variant="secondary">
                    <a href={meet} target="_blank" rel="noreferrer noopener">
                      <ExternalLink />
                      {t("openMeet")}
                    </a>
                  </Button>
                ) : null}
                <p className="text-xs text-fg-muted">{t("tokenHint")}</p>
              </div>
            ) : null}
          </>
        )}
      </CardBody>
    </Card>
  );
}

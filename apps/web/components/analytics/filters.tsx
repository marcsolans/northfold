"use client";

import { Button, Input, Select, cn } from "@messer/ui";
import { RefreshCw, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import type { AnalyticsQuery } from "./queries";
import type { FilterOptions } from "./types";

export const RANGE_PRESETS = ["24h", "7d", "30d", "90d", "custom"] as const;
export type RangePreset = (typeof RANGE_PRESETS)[number];

const PRESET_MS: Record<Exclude<RangePreset, "custom">, number> = {
  "24h": 24 * 3600_000,
  "7d": 7 * 86400_000,
  "30d": 30 * 86400_000,
  "90d": 90 * 86400_000,
};

const ALL = "__all__";

export interface AnalyticsFilterState {
  range: RangePreset;
  from: string;
  to: string;
  project: string | null;
  environment: string | null;
  channel: string | null;
  agent: string | null;
}

function isPreset(value: string | null): value is RangePreset {
  return value !== null && (RANGE_PRESETS as readonly string[]).includes(value);
}

function isoDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function localMidnight(day: string, addDays = 0): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + addDays, 0, 0, 0, 0);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Madrid";
  } catch {
    return "Europe/Madrid";
  }
}

/**
 * Filter state lives in the URL (shareable, survives reloads). Presets are relative to an anchor time that only
 * moves when the user changes the range or presses refresh, so query keys stay stable between renders.
 */
export function useAnalyticsFilters(fixedProjectId?: string) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [anchor, setAnchor] = React.useState(() => Math.ceil(Date.now() / 60_000) * 60_000);

  const rawRange = params.get("range");
  const state: AnalyticsFilterState = {
    range: isPreset(rawRange) ? rawRange : "30d",
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
    project: fixedProjectId ?? params.get("project"),
    environment: params.get("env"),
    channel: params.get("channel"),
    agent: params.get("agent"),
  };

  const { range, from, to, project, environment, channel, agent } = state;
  const { query, valid } = React.useMemo(() => {
    let since: Date | null;
    let until: Date | null;
    if (range === "custom") {
      since = localMidnight(from);
      until = localMidnight(to, 1);
    } else {
      until = new Date(anchor);
      since = new Date(anchor - PRESET_MS[range]);
    }
    const ok = since !== null && until !== null && since < until;
    const fallbackUntil = new Date(anchor);
    const q: AnalyticsQuery = {
      since: (ok && since ? since : new Date(anchor - PRESET_MS["30d"])).toISOString(),
      until: (ok && until ? until : fallbackUntil).toISOString(),
      tz: browserTimeZone(),
      project_id: project ?? undefined,
      environment: environment ?? undefined,
      channel: channel ?? undefined,
      workforce: agent ?? undefined,
    };
    return { query: q, valid: ok };
  }, [range, from, to, project, environment, channel, agent, anchor]);

  const update = React.useCallback(
    (patch: Partial<Record<"range" | "from" | "to" | "project" | "env" | "channel" | "agent", string | null>>) => {
      const next = new URLSearchParams(params.toString());
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === "" || value === undefined) next.delete(key);
        else next.set(key, value);
      }
      if (patch.range && patch.range !== "custom") {
        next.delete("from");
        next.delete("to");
        setAnchor(Math.ceil(Date.now() / 60_000) * 60_000);
      }
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  const refresh = React.useCallback(() => setAnchor(Math.ceil(Date.now() / 60_000) * 60_000), []);
  const hasFilters = Boolean((!fixedProjectId && project) || environment || channel || agent);
  return { state, query, valid, update, refresh, hasFilters };
}

export type AnalyticsFilters = ReturnType<typeof useAnalyticsFilters>;

/** One filter row above everything it scopes: period first, then project, environment, channel and agent. */
export function AnalyticsFilterBar({
  filters,
  options,
  showProject,
  refreshing,
}: {
  filters: AnalyticsFilters;
  options: FilterOptions | undefined;
  showProject: boolean;
  refreshing: boolean;
}) {
  const t = useTranslations("analytics.filters");
  const tl = useTranslations("analytics");
  const { state, update, refresh, valid, hasFilters } = filters;

  const startCustom = () => {
    const today = new Date();
    const start = new Date(today.getTime() - 6 * 86400_000);
    update({ range: "custom", from: state.from || isoDay(start), to: state.to || isoDay(today) });
  };

  const envOptions = Array.from(new Set([...(options?.environments ?? []), ...(state.environment ? [state.environment] : [])]));
  const channelOptions = Array.from(new Set([...(options?.channels ?? []), ...(state.channel ? [state.channel] : [])]));
  const agents = options?.agents ?? [];
  const agentOptions = state.agent && !agents.some((a) => a.value === state.agent) ? [...agents, { value: state.agent, label: state.agent }] : agents;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-end gap-2" role="group" aria-label={t("label")}>
        <div className="w-44">
          <Select
            aria-label={t("range")}
            value={state.range}
            onValueChange={(value) => (value === "custom" ? startCustom() : update({ range: value }))}
            options={RANGE_PRESETS.map((p) => ({ value: p, label: t(`presets.${p}`) }))}
          />
        </div>
        {state.range === "custom" ? (
          <div className="flex items-center gap-1.5">
            <Input
              type="date"
              aria-label={t("from")}
              className="h-8 w-36"
              value={state.from}
              max={state.to || undefined}
              onChange={(e) => update({ from: e.target.value })}
            />
            <span className="text-fg-subtle" aria-hidden>
              –
            </span>
            <Input
              type="date"
              aria-label={t("to")}
              className="h-8 w-36"
              value={state.to}
              min={state.from || undefined}
              onChange={(e) => update({ to: e.target.value })}
            />
          </div>
        ) : null}
        {showProject ? (
          <div className="w-48">
            <Select
              aria-label={t("project")}
              value={state.project ?? ALL}
              onValueChange={(value) => update({ project: value === ALL ? null : value, agent: null })}
              options={[{ value: ALL, label: t("allProjects") }, ...(options?.projects ?? []).map((p) => ({ value: p.value, label: p.label }))]}
            />
          </div>
        ) : null}
        <div className="w-48">
          <Select
            aria-label={t("environment")}
            value={state.environment ?? ALL}
            onValueChange={(value) => update({ env: value === ALL ? null : value })}
            options={[
              { value: ALL, label: t("allEnvironments") },
              ...envOptions.map((e) => ({ value: e, label: tl.has(`environments.${e}`) ? tl(`environments.${e}`) : e })),
            ]}
          />
        </div>
        <div className="w-44">
          <Select
            aria-label={t("channel")}
            value={state.channel ?? ALL}
            onValueChange={(value) => update({ channel: value === ALL ? null : value })}
            options={[
              { value: ALL, label: t("allChannels") },
              ...channelOptions.map((c) => ({ value: c, label: tl.has(`channels.${c}`) ? tl(`channels.${c}`) : c })),
            ]}
          />
        </div>
        <div className="w-44">
          <Select
            aria-label={t("agent")}
            value={state.agent ?? ALL}
            onValueChange={(value) => update({ agent: value === ALL ? null : value })}
            options={[{ value: ALL, label: t("allAgents") }, ...agentOptions.map((a) => ({ value: a.value, label: a.label }))]}
          />
        </div>
        <div className="ml-auto flex items-center gap-1">
          {hasFilters ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => update(showProject ? { project: null, env: null, channel: null, agent: null } : { env: null, channel: null, agent: null })}
            >
              <X />
              {t("reset")}
            </Button>
          ) : null}
          <Button variant="secondary" size="sm" onClick={refresh} aria-label={t("refresh")} disabled={state.range === "custom"}>
            <RefreshCw className={cn(refreshing && "animate-spin")} />
            {t("refresh")}
          </Button>
        </div>
      </div>
      {!valid ? (
        <p className="text-xs text-danger" role="alert">
          {t("invalidRange")}
        </p>
      ) : null}
    </div>
  );
}

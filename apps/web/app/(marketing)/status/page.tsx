import { Badge, Button, StatusDot, type StatusTone, cn } from "@messer/ui";
import { RefreshCw } from "lucide-react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { Container, SectionHeader } from "@/components/marketing/section";
import { localeTag } from "@/lib/format";
import { type PublicStatus, type ServiceStatus, getPublicStatus } from "@/lib/marketing/public-api";
import { currentLocale, pageMetadata } from "@/lib/marketing/site";

type DayStatus = PublicStatus["services"][number]["days"][number]["status"];

const TONE: Record<ServiceStatus, StatusTone> = {
  operational: "success",
  degraded: "warning",
  down: "danger",
  unknown: "neutral",
};

const BAR: Record<DayStatus, string> = {
  operational: "bg-success",
  degraded: "bg-warning",
  down: "bg-danger",
  no_data: "bg-muted",
};

const BANNER: Record<ServiceStatus, string> = {
  operational: "border-success/25 bg-success-soft",
  degraded: "border-warning/25 bg-warning-soft",
  down: "border-danger/25 bg-danger-soft",
  unknown: "border-border bg-subtle",
};

const KNOWN_SERVICES = ["web", "api", "runtime", "worker", "scheduler", "voice", "mcp"];

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("status");
  return pageMetadata({
    title: t("metaTitle"),
    description: t("metaDescription"),
    path: "/status",
    locale: await currentLocale(),
  });
}

export default async function StatusPage() {
  const t = await getTranslations("status");
  const locale = localeTag(await currentLocale());
  const result = await getPublicStatus();
  const pct = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  const dateTime = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" });
  const dateOnly = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" });

  const serviceName = (key: string) => (KNOWN_SERVICES.includes(key) ? t(`services.${key}`) : key);
  const duration = (start: string, end: string | null) => {
    const minutes = Math.max(1, Math.round(((end ? Date.parse(end) : Date.now()) - Date.parse(start)) / 60000));
    if (minutes < 60) return t("duration.minutes", { count: minutes });
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return rest ? t("duration.hoursMinutes", { hours, minutes: rest }) : t("duration.hours", { count: hours });
  };

  return (
    <Container className="max-w-4xl py-14 sm:py-20">
      <SectionHeader as="h1" eyebrow={t("eyebrow")} title={t("title")} />

      {!result.ok ? (
        <div role="alert" className="mt-8 rounded-md border border-warning/25 bg-warning-soft p-5">
          <p className="text-base font-semibold text-fg">{t("unavailableTitle")}</p>
          <p className="mt-1 text-sm text-fg-muted">{t("unavailableBody")}</p>
          <Button asChild variant="secondary" size="sm" className="mt-4">
            <a href="/status">
              <RefreshCw />
              {t("refresh")}
            </a>
          </Button>
        </div>
      ) : (
        <>
          <div className={cn("mt-8 flex flex-col gap-3 rounded-md border p-5 sm:flex-row sm:items-center sm:justify-between", BANNER[result.data.status])}>
            <div className="flex items-center gap-3">
              <StatusDot tone={TONE[result.data.status]} className="size-2.5" />
              <div>
                <p className="text-base font-semibold text-fg">{t(`overall.${result.data.status}`)}</p>
                <p className="mt-0.5 text-sm text-fg-muted">
                  {result.data.updated_at ? t("updated", { time: dateTime.format(new Date(result.data.updated_at)) }) : t("never")}
                </p>
              </div>
            </div>
            <Button asChild variant="secondary" size="sm">
              <a href="/status">
                <RefreshCw />
                {t("refresh")}
              </a>
            </Button>
          </div>

          <h2 className="mt-10 text-md font-semibold text-fg">{t("servicesTitle")}</h2>
          <ul className="mt-3 divide-y divide-border rounded-md border border-border bg-surface">
            {result.data.services.map((service) => {
              const uptime =
                service.uptime_90d === null ? t("uptimeUnknown") : t("uptime", { pct: pct.format(service.uptime_90d) });
              return (
                <li key={service.key} className="px-4 py-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-fg">{serviceName(service.key)}</p>
                    <div className="flex items-center gap-2">
                      {service.latency_ms !== null ? (
                        <span className="tabular text-xs text-fg-subtle">{t("latency", { ms: service.latency_ms })}</span>
                      ) : null}
                      <Badge tone={TONE[service.status] === "neutral" ? "neutral" : TONE[service.status]}>
                        <StatusDot tone={TONE[service.status]} className="size-1.5" />
                        {t(`statuses.${service.status}`)}
                      </Badge>
                    </div>
                  </div>
                  <div className="mt-3 flex h-8 items-stretch gap-px" role="img" aria-label={`${serviceName(service.key)}: ${uptime}`}>
                    {service.days.map((day) => {
                      const date = dateOnly.format(new Date(`${day.date}T00:00:00Z`));
                      const label =
                        day.uptime === null
                          ? t("day", { date, status: t(`statuses.${day.status}`) })
                          : t("dayWithUptime", { date, status: t(`legend.${day.status}`), pct: pct.format(day.uptime) });
                      return <span key={day.date} title={label} aria-hidden className={cn("min-w-0 flex-1 rounded-[1px]", BAR[day.status])} />;
                    })}
                  </div>
                  <div className="mt-1.5 flex justify-between text-[11px] text-fg-subtle">
                    <span>{t("ninetyDaysAgo")}</span>
                    <span className="tabular">{uptime}</span>
                    <span>{t("today")}</span>
                  </div>
                </li>
              );
            })}
          </ul>

          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-muted">
            {(["operational", "degraded", "down", "no_data"] as const).map((key) => (
              <li key={key} className="flex items-center gap-1.5">
                <span aria-hidden className={cn("inline-block h-3 w-1.5 rounded-[1px]", BAR[key])} />
                {t(`legend.${key}`)}
              </li>
            ))}
          </ul>

          <h2 className="mt-10 text-md font-semibold text-fg">{t("incidentsTitle")}</h2>
          {result.data.incidents.length === 0 ? (
            <p className="mt-3 rounded-md border border-dashed border-border-strong px-4 py-6 text-center text-sm text-fg-muted">
              {t("noIncidents")}
            </p>
          ) : (
            <ul className="mt-3 divide-y divide-border rounded-md border border-border bg-surface">
              {result.data.incidents.map((incident) => (
                <li key={`${incident.service}-${incident.started_at}`} className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm font-medium text-fg">
                      {serviceName(incident.service)} · {t(`incident.${incident.status}`)}
                    </p>
                    <p className="text-xs text-fg-muted">
                      {t("incident.started", { time: dateTime.format(new Date(incident.started_at)) })}
                      {incident.resolved_at ? ` · ${t("incident.ended", { time: dateTime.format(new Date(incident.resolved_at)) })}` : ""}
                      {` · ${t("incident.duration", { duration: duration(incident.started_at, incident.resolved_at) })}`}
                    </p>
                  </div>
                  <Badge tone={incident.resolved_at ? "success" : incident.status === "down" ? "danger" : "warning"}>
                    {incident.resolved_at ? t("incident.resolved") : t("incident.ongoing")}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <p className="mt-8 text-xs text-fg-subtle">{t("note")}</p>
    </Container>
  );
}

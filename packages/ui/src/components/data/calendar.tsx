"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import * as React from "react";

import { cn } from "../../lib/cn";
import { Button } from "../button";
import { Skeleton } from "../skeleton";
import { DataStatus, type DataStateLabels } from "./data-state";
import { type DataRow, parseDate } from "./format";

export interface CalendarLabels extends DataStateLabels {
  previous: string;
  next: string;
  today: string;
  more: (count: number) => string;
}

interface CalendarEvent {
  start: Date;
  end: Date;
  title: string;
  index: number;
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** Month grid (Monday first) or agenda list of dated records. Weekday and month names come from Intl. */
export function CalendarView({
  rows,
  dateField,
  endField,
  titleField,
  view = "month",
  loading,
  error,
  onRetry,
  labels,
  locale = "es-ES",
  className,
}: {
  rows: DataRow[];
  dateField: string;
  endField?: string | null;
  titleField?: string | null;
  view?: "month" | "agenda";
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  labels: CalendarLabels;
  locale?: string;
  className?: string;
}) {
  const events = React.useMemo<CalendarEvent[]>(() => {
    const out: CalendarEvent[] = [];
    rows.forEach((row, index) => {
      const start = parseDate(row[dateField]);
      if (!start) return;
      const end = (endField ? parseDate(row[endField]) : null) ?? start;
      const titleKey = titleField || Object.keys(row).find((k) => k !== dateField && k !== endField) || dateField;
      const raw = row[titleKey];
      out.push({ start, end: end < start ? start : end, title: raw === null || raw === undefined ? "—" : String(raw), index });
    });
    return out.sort((a, b) => a.start.getTime() - b.start.getTime());
  }, [rows, dateField, endField, titleField]);

  const [cursor, setCursor] = React.useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  const monthTitle = new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }).format(cursor);
  const weekdays = React.useMemo(() => {
    const monday = new Date(2024, 0, 1); // a Monday
    return Array.from({ length: 7 }, (_, i) =>
      new Intl.DateTimeFormat(locale, { weekday: "short" }).format(new Date(monday.getTime() + i * 86_400_000)),
    );
  }, [locale]);

  const byDay = React.useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const ev of events) {
      for (let d = startOfDay(ev.start); d <= ev.end && map.size < 5000; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
        const key = dayKey(d);
        map.set(key, [...(map.get(key) ?? []), ev]);
      }
    }
    return map;
  }, [events]);

  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const offset = (first.getDay() + 6) % 7;
  const days = Array.from({ length: 42 }, (_, i) => new Date(cursor.getFullYear(), cursor.getMonth(), 1 - offset + i));
  const todayKey = dayKey(new Date());
  const monthEvents = events.filter(
    (e) =>
      e.end >= first &&
      e.start < new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1),
  );
  const dayFormat = new Intl.DateTimeFormat(locale, { weekday: "short", day: "numeric", month: "short" });

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col gap-2", className)}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold capitalize text-fg" aria-live="polite">
          {monthTitle}
        </p>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon-sm" aria-label={labels.previous} onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>
            <ChevronLeft />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setCursor(new Date(new Date().getFullYear(), new Date().getMonth(), 1))}>
            {labels.today}
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label={labels.next} onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>
            <ChevronRight />
          </Button>
        </div>
      </div>
      <DataStatus
        loading={loading}
        error={error}
        empty={!loading && !error && (view === "agenda" ? monthEvents.length === 0 : events.length === 0)}
        labels={labels}
        onRetry={onRetry}
        skeleton={<Skeleton className="h-full min-h-40 w-full" />}
      >
        {view === "agenda" ? (
          <ul className="flex min-h-0 flex-1 flex-col divide-y divide-border overflow-auto rounded-md border border-border">
            {monthEvents.map((e) => (
              <li key={e.index} className="flex gap-3 px-3 py-2 text-sm">
                <span className="tabular w-28 shrink-0 text-fg-muted">{dayFormat.format(e.start)}</span>
                <span className="min-w-0 truncate text-fg">{e.title}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-7 grid-rows-[auto_repeat(6,minmax(0,1fr))] overflow-hidden rounded-md border border-border text-xs">
            {weekdays.map((w) => (
              <div key={w} className="border-b border-border bg-subtle px-1.5 py-1 font-medium uppercase text-fg-subtle">
                {w}
              </div>
            ))}
            {days.map((d) => {
              const key = dayKey(d);
              const items = byDay.get(key) ?? [];
              const inMonth = d.getMonth() === cursor.getMonth();
              return (
                <div
                  key={key}
                  className={cn("flex min-h-12 flex-col gap-0.5 border-b border-r border-border p-1", !inMonth && "bg-subtle/60")}
                >
                  <span
                    className={cn(
                      "tabular inline-flex size-5 items-center justify-center rounded-full",
                      inMonth ? "text-fg" : "text-fg-subtle",
                      key === todayKey && "bg-accent text-accent-fg",
                    )}
                  >
                    {d.getDate()}
                  </span>
                  {items.slice(0, 2).map((e) => (
                    <span key={e.index} className="truncate rounded-sm border border-border bg-surface px-1 text-fg" title={e.title}>
                      {e.title}
                    </span>
                  ))}
                  {items.length > 2 ? <span className="text-fg-subtle">{labels.more(items.length - 2)}</span> : null}
                </div>
              );
            })}
          </div>
        )}
      </DataStatus>
    </div>
  );
}

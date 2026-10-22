"use client";

import { Badge, StatusDot, type StatusTone } from "@messer/ui";
import { useTranslations } from "next-intl";

const TONES: Record<string, StatusTone> = {
  uploading: "info",
  queued: "neutral",
  parsing: "info",
  chunking: "info",
  embedding: "info",
  indexing: "info",
  ready: "success",
  error: "danger",
};

export function isProcessing(status: string): boolean {
  return status !== "ready" && status !== "error";
}

/** File ingestion status with a progress bar while it is being processed. */
export function FileStatus({ status, progress, error }: { status: string; progress?: number; error?: string | null }) {
  const t = useTranslations("knowledge.files.status");
  const tone = TONES[status] ?? "neutral";
  const processing = isProcessing(status);
  const pct = Math.round(Math.max(0, Math.min(1, progress ?? 0)) * 100);
  return (
    <div className="flex min-w-36 flex-col gap-1" title={error ?? undefined}>
      <span className="flex items-center gap-1.5">
        {processing ? <StatusDot tone={tone} pulse /> : null}
        <Badge tone={tone}>{t(status)}</Badge>
        {processing && pct > 0 ? <span className="tabular text-xs text-fg-subtle">{pct}%</span> : null}
      </span>
      {processing ? (
        <div
          className="h-1 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label={t(status)}
        >
          <div className="h-full bg-info transition-[width] duration-300" style={{ width: `${Math.max(pct, 4)}%` }} />
        </div>
      ) : null}
      {status === "error" && error ? <span className="line-clamp-2 text-xs text-danger">{error}</span> : null}
    </div>
  );
}

"use client";

import { CheckCircle2, FileUp, Loader2, XCircle } from "lucide-react";
import * as React from "react";

import { cn } from "../../lib/cn";

export interface FileDropzoneLabels {
  drop: string;
  browse: string;
  limits: (accept: string, maxMb: number) => string;
  tooLarge: (maxMb: number) => string;
  unsupported: string;
  uploading: string;
  done: string;
  failed: string;
}

export interface UploadOutcome {
  ok: boolean;
  message?: string | null;
}

interface Item {
  id: string;
  name: string;
  state: "uploading" | "done" | "error";
  message: string | null;
}

/** Drop zone + file picker. Files are checked (type, size) and uploaded one by one with per-file status. */
export function FileDropzone({
  accept = [],
  maxMb = 20,
  multiple = true,
  disabled = false,
  label,
  help,
  onUpload,
  labels,
  className,
}: {
  accept?: string[];
  maxMb?: number;
  multiple?: boolean;
  disabled?: boolean;
  label?: string | null;
  help?: string | null;
  onUpload: (file: File) => Promise<UploadOutcome>;
  labels: FileDropzoneLabels;
  className?: string;
}) {
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const [over, setOver] = React.useState(false);
  const [items, setItems] = React.useState<Item[]>([]);
  const inputId = React.useId();

  const update = (id: string, patch: Partial<Item>) => setItems((list) => list.map((i) => (i.id === id ? { ...i, ...patch } : i)));

  const handle = async (files: FileList | File[]) => {
    const list = Array.from(files).slice(0, multiple ? 20 : 1);
    for (const file of list) {
      const id = `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const lower = file.name.toLowerCase();
      if (accept.length > 0 && !accept.some((ext) => lower.endsWith(ext))) {
        setItems((l) => [...l, { id, name: file.name, state: "error", message: labels.unsupported }]);
        continue;
      }
      if (file.size > maxMb * 1024 * 1024) {
        setItems((l) => [...l, { id, name: file.name, state: "error", message: labels.tooLarge(maxMb) }]);
        continue;
      }
      setItems((l) => [...l, { id, name: file.name, state: "uploading", message: null }]);
      try {
        const res = await onUpload(file);
        update(id, { state: res.ok ? "done" : "error", message: res.message ?? null });
      } catch (err) {
        update(id, { state: "error", message: err instanceof Error ? err.message : labels.failed });
      }
    }
  };

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col gap-2", className)}>
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (!disabled && e.dataTransfer.files.length > 0) void handle(e.dataTransfer.files);
        }}
        className={cn(
          "flex min-h-24 flex-1 cursor-pointer flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border-strong px-4 py-4 text-center text-sm transition-colors",
          over && "border-accent bg-accent-soft",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        <FileUp className="size-5 text-fg-subtle" aria-hidden />
        <span className="font-medium text-fg">{label || labels.drop}</span>
        <span className="text-xs text-fg-muted">
          <span className="text-accent underline underline-offset-4">{labels.browse}</span>
          {" · "}
          {labels.limits(accept.join(", "), maxMb)}
        </span>
        {help ? <span className="text-xs text-fg-subtle">{help}</span> : null}
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          className="sr-only"
          multiple={multiple}
          disabled={disabled}
          accept={accept.length > 0 ? accept.join(",") : undefined}
          onChange={(e) => {
            if (e.target.files) void handle(e.target.files);
            e.target.value = "";
          }}
        />
      </label>
      {items.length > 0 ? (
        <ul className="flex flex-col gap-1 text-xs" aria-live="polite">
          {items.map((i) => (
            <li key={i.id} className="flex items-center gap-2">
              {i.state === "uploading" ? (
                <Loader2 className="size-3.5 animate-spin text-fg-subtle" aria-hidden />
              ) : i.state === "done" ? (
                <CheckCircle2 className="size-3.5 text-success" aria-hidden />
              ) : (
                <XCircle className="size-3.5 text-danger" aria-hidden />
              )}
              <span className="min-w-0 truncate text-fg">{i.name}</span>
              <span className={cn("ml-auto shrink-0", i.state === "error" ? "text-danger" : "text-fg-muted")}>
                {i.message || (i.state === "uploading" ? labels.uploading : i.state === "done" ? labels.done : labels.failed)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

"use client";

import { Badge, Button, Kbd, Spinner, Textarea, toast } from "@messer/ui";
import { FileText, Paperclip, Send, Square, X } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { nextKey } from "@/lib/studio/chat";
import { errorMessage } from "@/lib/studio/hooks";
import type { Upload } from "@/lib/studio/types";

const MAX_ATTACHMENTS = 10;
const MAX_BYTES = 20 * 1024 * 1024;

interface PendingAttachment {
  key: string;
  name: string;
  size: number;
  status: "uploading" | "ready" | "error";
  upload: Upload | null;
  error: string | null;
}

export function Composer({
  projectId,
  disabled,
  disabledReason,
  streaming,
  onSend,
  onStop,
}: {
  projectId: string;
  disabled: boolean;
  disabledReason: string | null;
  streaming: boolean;
  onSend: (text: string, attachments: Upload[]) => void;
  onStop: () => void;
}) {
  const t = useTranslations("studio.playground.composer");
  const tc = useTranslations("common");
  const [text, setText] = React.useState("");
  const [attachments, setAttachments] = React.useState<PendingAttachment[]>([]);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const textRef = React.useRef<HTMLTextAreaElement>(null);

  const uploading = attachments.some((a) => a.status === "uploading");
  const canSend = !disabled && !streaming && !uploading && text.trim().length > 0;

  const send = () => {
    if (!canSend) return;
    const ready = attachments.filter((a) => a.status === "ready" && a.upload).map((a) => a.upload as Upload);
    onSend(text.trim(), ready);
    setText("");
    setAttachments([]);
    requestAnimationFrame(() => textRef.current?.focus());
  };

  const addFiles = (files: FileList | null) => {
    const list = Array.from(files ?? []);
    if (fileRef.current) fileRef.current.value = "";
    if (attachments.length + list.length > MAX_ATTACHMENTS) {
      toast.error(t("tooMany", { max: MAX_ATTACHMENTS }));
      return;
    }
    for (const file of list) {
      if (file.size > MAX_BYTES) {
        toast.error(t("tooLarge", { name: file.name }));
        continue;
      }
      const key = nextKey("att");
      setAttachments((prev) => [...prev, { key, name: file.name, size: file.size, status: "uploading", upload: null, error: null }]);
      const form = new FormData();
      form.append("file", file);
      http.post<Upload>(`/projects/${projectId}/uploads`, form).then(
        (upload) =>
          setAttachments((prev) => prev.map((a) => (a.key === key ? { ...a, status: "ready", upload, name: upload.name } : a))),
        (err: unknown) =>
          setAttachments((prev) =>
            prev.map((a) => (a.key === key ? { ...a, status: "error", error: errorMessage(err, tc("errorGeneric")) } : a)),
          ),
      );
    }
  };

  return (
    <form
      className="border-t border-border bg-bg p-3"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      {disabledReason ? <p className="mb-2 text-xs text-fg-subtle">{disabledReason}</p> : null}
      {attachments.length > 0 ? (
        <ul className="mb-2 flex flex-wrap gap-1.5" aria-label={t("attachments")}>
          {attachments.map((a) => (
            <li key={a.key}>
              <Badge tone={a.status === "error" ? "danger" : "outline"} className="gap-1 py-0.5" title={a.error ?? undefined}>
                {a.status === "uploading" ? <Spinner className="size-3 border" label={t("uploading")} /> : <FileText className="size-3" aria-hidden />}
                <span className="max-w-40 truncate">{a.name}</span>
                {a.status === "error" ? <span className="sr-only">{a.error}</span> : null}
                <button
                  type="button"
                  className="rounded-sm p-0.5 hover:bg-muted"
                  aria-label={t("removeAttachment", { name: a.name })}
                  onClick={() => setAttachments((prev) => prev.filter((x) => x.key !== a.key))}
                >
                  <X className="size-3" />
                </button>
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex items-end gap-2">
        <input
          ref={fileRef}
          type="file"
          multiple
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => addFiles(e.target.files)}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("attach")}
          disabled={disabled || streaming}
          onClick={() => fileRef.current?.click()}
        >
          <Paperclip />
        </Button>
        <label htmlFor="playground-input" className="sr-only">
          {t("label")}
        </label>
        <Textarea
          id="playground-input"
          ref={textRef}
          value={text}
          rows={1}
          disabled={disabled}
          placeholder={t("placeholder")}
          className="max-h-48 min-h-9 flex-1 resize-none py-1.5"
          onChange={(e) => {
            setText(e.target.value);
            const el = e.target;
            el.style.height = "auto";
            el.style.height = `${Math.min(el.scrollHeight, 192)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        {streaming ? (
          <Button type="button" variant="secondary" onClick={onStop} aria-label={t("stop")}>
            <Square />
            {t("stop")}
          </Button>
        ) : (
          <Button type="submit" variant="primary" disabled={!canSend} aria-label={t("send")}>
            <Send />
            {t("send")}
          </Button>
        )}
      </div>
      <p className="mt-1.5 flex items-center gap-1 text-[11px] text-fg-subtle">
        <Kbd>Enter</Kbd> {t("sendHint")} · <Kbd>Shift</Kbd>+<Kbd>Enter</Kbd> {t("newlineHint")}
      </p>
    </form>
  );
}

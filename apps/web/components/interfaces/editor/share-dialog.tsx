"use client";

import { Alert, CodeBlock, CopyButton, Dialog, DialogContent, Field, Input } from "@messer/ui";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import type { InterfaceUrls } from "../types";

/** Public URL, embeddable page and the one-line widget snippet of an interface. */
export function ShareDialog({
  open,
  onOpenChange,
  urls,
  published,
  kind,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  urls: InterfaceUrls;
  published: boolean;
  kind: "app" | "chat";
}) {
  const t = useTranslations("interfaces.share");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("title")} description={kind === "chat" ? t("descriptionChat") : t("descriptionApp")}>
        <div className="flex flex-col gap-4">
          {!published ? <Alert tone="warning" title={t("notPublishedTitle")}>{t("notPublished")}</Alert> : null}
          {urls.public ? (
            <Field label={t("publicUrl")}>
              <div className="flex items-center gap-1">
                <Input readOnly value={urls.public} aria-label={t("publicUrl")} className="font-mono text-xs" />
                <CopyButton value={urls.public} label={t("copy")} />
                {published ? (
                  <a href={urls.public} target="_blank" rel="noreferrer" className="inline-flex size-7 items-center justify-center rounded-md text-fg-muted hover:bg-subtle" aria-label={t("open")}>
                    <ExternalLink className="size-4" />
                  </a>
                ) : null}
              </div>
            </Field>
          ) : null}
          {urls.embed ? (
            <Field label={t("embedUrl")} hint={t("embedHint")}>
              <div className="flex items-center gap-1">
                <Input readOnly value={urls.embed} aria-label={t("embedUrl")} className="font-mono text-xs" />
                <CopyButton value={urls.embed} label={t("copy")} />
              </div>
            </Field>
          ) : null}
          {urls.widget ? (
            <div className="flex flex-col gap-1.5">
              <p className="text-sm font-medium text-fg">{t("widget")}</p>
              <p className="text-xs text-fg-muted">{t("widgetHint")}</p>
              <CodeBlock code={urls.widget} language="html" />
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

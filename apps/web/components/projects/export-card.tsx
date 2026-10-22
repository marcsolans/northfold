"use client";

import { Alert, Button, Card, CardBody, CardFooter, CardHeader, Field, Select, Skeleton, toast } from "@messer/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Download } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { apiFetch, http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";
import { useRole } from "@/lib/hooks/use-me";
import { errorMessage } from "@/lib/studio/hooks";

interface CommitEntry {
  sha: string;
  message: string;
  author: string;
  date: string;
}

const HEAD = "HEAD";

function filenameFrom(disposition: string | null, fallback: string): string {
  const match = /filename="?([^";]+)"?/i.exec(disposition ?? "");
  return match?.[1] ?? fallback;
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** "Export" section of the project settings page: download a self-contained .zip at a chosen version. */
export function ExportCard({ projectId }: { projectId: string }) {
  const t = useTranslations("github.export");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const canExport = useRole("builder");
  const [ref, setRef] = React.useState(HEAD);

  const commits = useQuery({
    queryKey: ["projects", projectId, "commits", { limit: 30 }],
    queryFn: () => http.get<CommitEntry[]>(`/projects/${projectId}/commits`, { limit: 30 }),
    enabled: canExport,
  });

  const download = useMutation({
    mutationFn: async () => {
      const res = await apiFetch(`/projects/${projectId}/export.zip`, {
        query: { ref },
        headers: { Accept: "application/zip" },
      });
      const blob = await res.blob();
      const name = filenameFrom(res.headers.get("content-disposition"), "proyecto.zip");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
      return name;
    },
    onSuccess: (name) => toast.success(t("downloaded"), { description: name }),
    onError: (err) => toast.error(errorMessage(err, tc("errorGeneric"))),
  });

  const options = [
    { value: HEAD, label: t("latest") },
    ...(commits.data ?? []).map((c) => ({
      value: c.sha,
      label: `${c.sha.slice(0, 7)} · ${truncate(c.message, 60)}`,
      description: `${c.author} · ${formatDate(c.date, locale, true)}`,
    })),
  ];

  const includes = [t("includeCode"), t("includeKnowledge"), t("includeRuntime"), t("includeDocs")];

  return (
    <Card>
      <CardHeader title={t("title")} description={t("description")} />
      <CardBody className="flex flex-col gap-4">
        <div>
          <p className="mb-1.5 text-sm font-medium">{t("includes")}</p>
          <ul className="flex flex-col gap-1 text-sm text-fg-muted">
            {includes.map((item) => (
              <li key={item} className="flex items-start gap-2">
                <Check className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
                <span>{item}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-fg-subtle">{t("excludes")}</p>
        </div>
        {!canExport ? (
          <Alert tone="info">{t("readOnly")}</Alert>
        ) : (
          <Field label={t("version")} htmlFor="export-ref">
            {commits.isLoading ? (
              <Skeleton className="h-8 w-full" />
            ) : (
              <Select id="export-ref" value={ref} onValueChange={setRef} options={options} disabled={download.isPending} />
            )}
          </Field>
        )}
        {canExport && commits.error ? <Alert tone="warning">{t("commitsError")}</Alert> : null}
      </CardBody>
      {canExport ? (
        <CardFooter>
          {download.isPending ? <span className="mr-auto text-xs text-fg-muted">{t("preparing")}</span> : null}
          <Button variant="primary" loading={download.isPending} onClick={() => download.mutate()}>
            <Download />
            {t("download")}
          </Button>
        </CardFooter>
      ) : null}
    </Card>
  );
}

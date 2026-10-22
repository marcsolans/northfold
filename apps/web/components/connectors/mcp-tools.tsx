"use client";

import { Badge, Button, EmptyState, ErrorState, SkeletonRows } from "@messer/ui";
import { RefreshCw, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";

import { errorMessage, useMcpTools } from "./queries";

export function McpTools({ connectionId }: { connectionId: string }) {
  const t = useTranslations("connectors.tools");
  const tc = useTranslations("common");
  const tools = useMcpTools(connectionId, true);
  if (tools.isLoading) return <SkeletonRows rows={4} />;
  if (tools.error) {
    return <ErrorState title={tc("errorTitle")} description={errorMessage(tools.error)} onRetry={() => void tools.refetch()} retryLabel={tc("retry")} />;
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <Button size="sm" variant="secondary" onClick={() => void tools.refetch()} loading={tools.isFetching}>
          <RefreshCw />
          {t("refresh")}
        </Button>
      </div>
      {(tools.data ?? []).length === 0 ? (
        <EmptyState icon={<Wrench />} title={t("empty")} />
      ) : (
        <ul className="grid gap-2 md:grid-cols-2">
          {(tools.data ?? []).map((tool) => (
            <li key={tool.name} className="flex flex-col gap-1 rounded-md border border-border bg-surface p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-sm font-medium">{tool.name}</span>
                <Badge tone={tool.read_only ? "neutral" : "warning"}>{tool.read_only ? t("readOnly") : t("sideEffect")}</Badge>
              </div>
              {tool.title && tool.title !== tool.name ? <span className="text-sm text-fg">{tool.title}</span> : null}
              {tool.description ? <p className="text-xs text-fg-muted">{tool.description}</p> : null}
              {Object.keys(tool.input_schema.properties ?? {}).length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {Object.keys(tool.input_schema.properties ?? {}).map((p) => (
                    <Badge key={p} tone="outline" className="font-mono">
                      {p}
                    </Badge>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

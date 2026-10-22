"use client";

import { Alert, Button, Dialog, DialogContent, Field, Input, RadioCards, Select, toast } from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { useMembers } from "@/lib/studio/hooks";

import { interfaceKeys, useKbTables, useKnowledgeBases, useTemplates } from "./api";
import type { InterfaceDetail } from "./types";
import { messageOf } from "./util";

/** New interface from a template: blank dashboard, dashboard over a table, invoices dashboard or public chat. */
export function CreateInterfaceDialog({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("interfaces.create");
  const tc = useTranslations("common");
  const locale = useLocale();
  const router = useRouter();
  const qc = useQueryClient();
  const templates = useTemplates();
  const kbs = useKnowledgeBases(projectId);
  const agents = useMembers(projectId, "agent");
  const [template, setTemplate] = React.useState("table_dashboard");
  const [name, setName] = React.useState("");
  const [kbId, setKbId] = React.useState("");
  const [table, setTable] = React.useState("");
  const [agent, setAgent] = React.useState("");
  const tables = useKbTables(kbId || null);

  const info = templates.data?.find((x) => x.key === template);
  const requires = info?.requires ?? [];
  const missing =
    !name.trim() ||
    (requires.includes("kb_id") && !kbId) ||
    (requires.includes("table") && !table) ||
    (requires.includes("agent") && !agent);

  React.useEffect(() => {
    if (!open) return;
    setName("");
    setTable("");
  }, [open]);
  React.useEffect(() => {
    if (!kbId && kbs.data?.[0]) setKbId(kbs.data[0].id);
  }, [kbs.data, kbId]);
  React.useEffect(() => {
    if (!agent && agents.data?.[0]) setAgent(agents.data[0].name);
  }, [agents.data, agent]);

  const create = useMutation({
    mutationFn: () =>
      http.post<InterfaceDetail>(`/projects/${projectId}/interfaces`, {
        template,
        name: name.trim(),
        kb_id: requires.includes("kb_id") ? kbId : null,
        table: requires.includes("table") ? table : template === "invoices_dashboard" && table ? table : null,
        agent: requires.includes("agent") ? agent || null : null,
      }),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: interfaceKeys.list(projectId) });
      qc.setQueryData(interfaceKeys.detail(created.id), created);
      toast.success(t("created", { name: created.name }));
      onOpenChange(false);
      router.push(`/app/projects/${projectId}/interfaces/${created.id}`);
    },
    onError: (err) => toast.error(messageOf(err, tc("errorGeneric"))),
  });

  const en = locale === "en";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={t("title")}
        description={t("description")}
        wide
        footer={
          <>
            <Button variant="secondary" onClick={() => onOpenChange(false)}>
              {tc("cancel")}
            </Button>
            <Button variant="primary" loading={create.isPending} disabled={missing} onClick={() => create.mutate()}>
              {tc("create")}
            </Button>
          </>
        }
      >
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!missing) create.mutate();
          }}
        >
          <Field label={t("template")}>
            {templates.error ? (
              <Alert tone="danger">{messageOf(templates.error, tc("errorGeneric"))}</Alert>
            ) : (
              <RadioCards
                value={template}
                onValueChange={setTemplate}
                className="sm:grid-cols-2"
                options={(templates.data ?? []).map((x) => ({
                  value: x.key,
                  label: en ? x.name_en : x.name,
                  description: en ? x.description_en : x.description,
                }))}
              />
            )}
          </Field>
          <Field label={t("name")} htmlFor="interface-name">
            <Input id="interface-name" value={name} autoFocus onChange={(e) => setName(e.target.value)} placeholder={t("namePlaceholder")} maxLength={120} />
          </Field>
          {requires.includes("kb_id") ? (
            kbs.data && kbs.data.length === 0 ? (
              <Alert tone="warning" title={t("noKbTitle")}>
                {t("noKb")}
              </Alert>
            ) : (
              <Field label={t("knowledgeBase")} htmlFor="interface-kb">
                <Select
                  id="interface-kb"
                  aria-label={t("knowledgeBase")}
                  value={kbId || undefined}
                  onValueChange={(v) => {
                    setKbId(v);
                    setTable("");
                  }}
                  placeholder={t("chooseKb")}
                  options={(kbs.data ?? []).map((k) => ({ value: k.id, label: k.name }))}
                />
              </Field>
            )
          ) : null}
          {(requires.includes("table") || template === "invoices_dashboard") && kbId ? (
            <Field label={requires.includes("table") ? t("table") : t("invoicesTable")} htmlFor="interface-table" hint={template === "invoices_dashboard" ? t("invoicesHint") : undefined}>
              <Select
                id="interface-table"
                aria-label={t("table")}
                value={table || undefined}
                onValueChange={setTable}
                placeholder={tables.isPending ? tc("loading") : t("chooseTable")}
                options={(tables.data ?? []).map((x) => ({ value: x.name, label: `${x.name} (${x.row_count})` }))}
              />
            </Field>
          ) : null}
          {requires.includes("agent") ? (
            agents.data && agents.data.length === 0 ? (
              <Alert tone="warning" title={t("noAgentTitle")}>
                {t("noAgent")}
              </Alert>
            ) : (
              <Field label={t("agent")} htmlFor="interface-agent">
                <Select
                  id="interface-agent"
                  aria-label={t("agent")}
                  value={agent || undefined}
                  onValueChange={setAgent}
                  placeholder={t("chooseAgent")}
                  options={(agents.data ?? []).map((a) => ({ value: a.name, label: a.name }))}
                />
              </Field>
            )
          ) : null}
        </form>
      </DialogContent>
    </Dialog>
  );
}

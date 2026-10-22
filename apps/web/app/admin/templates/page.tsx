"use client";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonRows,
  Switch,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, LayoutTemplate } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { ADMIN_KEY, type AdminTemplate } from "@/components/admin/types";
import { errorText } from "@/components/billing";
import { http } from "@/lib/api";

const TEMPLATES_KEY = [...ADMIN_KEY, "templates"] as const;

export default function AdminTemplatesPage() {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const locale = useLocale();
  const qc = useQueryClient();
  const templates = useQuery({ queryKey: TEMPLATES_KEY, queryFn: () => http.get<AdminTemplate[]>("/admin/templates") });
  const toggle = useMutation({
    mutationFn: ({ id, value }: { id: string; value: boolean }) => http.patch<AdminTemplate>(`/admin/templates/${id}`, { public: value }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: TEMPLATES_KEY }),
    onError: (err) => toast.error(errorText(err)),
  });
  const reorder = useMutation({
    mutationFn: (ids: string[]) => http.put<AdminTemplate[]>("/admin/templates/order", { ids }),
    onSuccess: (rows) => qc.setQueryData(TEMPLATES_KEY, rows),
    onError: (err) => toast.error(errorText(err)),
  });
  const move = (index: number, delta: number) => {
    const list = [...(templates.data ?? [])];
    const target = index + delta;
    if (target < 0 || target >= list.length) return;
    const [item] = list.splice(index, 1);
    if (!item) return;
    list.splice(target, 0, item);
    reorder.mutate(list.map((x) => x.id));
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("templates.title")} description={t("templates.description")} />
      <Card>
        {templates.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={6} />
          </div>
        ) : templates.error || !templates.data ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void templates.refetch()} />
          </div>
        ) : templates.data.length === 0 ? (
          <div className="p-4">
            <EmptyState icon={<LayoutTemplate />} title={t("templates.emptyTitle")} description={t("templates.empty")} />
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH className="w-24">{t("templates.order")}</TH>
                <TH>{tc("name")}</TH>
                <TH className="hidden md:table-cell">{t("templates.sector")}</TH>
                <TH>{t("templates.public")}</TH>
              </tr>
            </THead>
            <TBody>
              {templates.data.map((tpl, index, all) => (
                <TR key={tpl.id}>
                  <TD>
                    <div className="flex gap-0.5">
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={t("templates.moveUp")}
                        disabled={index === 0 || reorder.isPending}
                        onClick={() => move(index, -1)}
                      >
                        <ArrowUp />
                      </Button>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={t("templates.moveDown")}
                        disabled={index === all.length - 1 || reorder.isPending}
                        onClick={() => move(index, 1)}
                      >
                        <ArrowDown />
                      </Button>
                    </div>
                  </TD>
                  <TD>
                    <span className="font-medium">{locale === "en" && tpl.name_en ? tpl.name_en : tpl.name}</span>
                    <span className="block max-w-xl truncate text-xs text-fg-subtle">{tpl.description}</span>
                  </TD>
                  <TD className="hidden md:table-cell">
                    <Badge tone="outline">{tpl.sector}</Badge>
                  </TD>
                  <TD>
                    <Switch
                      checked={tpl.public}
                      aria-label={t("templates.public")}
                      disabled={toggle.isPending}
                      onCheckedChange={(value) => toggle.mutate({ id: tpl.id, value })}
                    />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}

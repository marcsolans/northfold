"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CopyButton,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Select,
  Skeleton,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { TypedConfirmDialog } from "@/components/enterprise/typed-confirm-dialog";
import type { DataRequest, ResidencyOverview } from "@/components/enterprise/types";
import { ApiError, http } from "@/lib/api";
import { useInvalidateMe, useRole } from "@/lib/hooks/use-me";
import type { OrgSummary } from "@/lib/types";

export default function OrganizationSettingsPage() {
  const t = useTranslations("enterprise.organization");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const invalidateMe = useInvalidateMe();
  const isAdmin = useRole("admin");
  const isOwner = useRole("owner");

  const org = useQuery({ queryKey: ["org", "current"], queryFn: () => http.get<OrgSummary>("/orgs/current") });
  const residency = useQuery({ queryKey: ["residency"], queryFn: () => http.get<ResidencyOverview>("/residency") });
  const [name, setName] = React.useState("");
  const [region, setRegion] = React.useState("");
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);
  const [deletion, setDeletion] = React.useState<DataRequest | null>(null);

  React.useEffect(() => {
    if (org.data) {
      setName(org.data.name);
      setRegion(org.data.region);
    }
  }, [org.data]);

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, string> = {};
      if (org.data && name.trim() !== org.data.name) body.name = name.trim();
      if (org.data && region !== org.data.region) body.region = region;
      return http.patch<OrgSummary>("/orgs/current", body);
    },
    onSuccess: async () => {
      toast.success(t("saved"));
      await Promise.all([qc.invalidateQueries({ queryKey: ["org"] }), qc.invalidateQueries({ queryKey: ["residency"] }), invalidateMe()]);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  const remove = useMutation({
    mutationFn: (confirm: string) => http.post<DataRequest>("/data-requests", { kind: "delete", scope: "org", confirm }),
    onSuccess: async (req) => {
      setDeleteOpen(false);
      setDeletion(req);
      toast.success(t("deleteRequested"));
      await invalidateMe();
    },
    onError: (err) => setDeleteError(err instanceof ApiError ? err.message : String(err)),
  });

  if (org.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-56 w-full" />
      </div>
    );
  }
  if (org.error || !org.data) {
    return <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void org.refetch()} />;
  }
  const current = org.data;
  const dirty = name.trim() !== current.name || region !== current.region;
  const regions = residency.data?.regions ?? [{ id: current.region, name: current.region }];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ts("organization")} description={t("description")} />

      {deletion ? (
        <Alert
          tone="warning"
          title={t("deleting")}
          action={
            <Button asChild size="sm" variant="secondary">
              <Link href="/app/settings/data">{t("followRequest")}</Link>
            </Button>
          }
        >
          {t("deleteRequested")}
        </Alert>
      ) : null}

      <Card>
        <CardHeader title={t("general")} />
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <Field label={t("name")} htmlFor="org-name">
            <Input id="org-name" value={name} maxLength={200} disabled={!isAdmin} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label={t("slug")} hint={t("slugHint")}>
            <div className="flex h-8 items-center gap-1 rounded-md border border-border bg-subtle px-2.5">
              <code className="min-w-0 flex-1 truncate font-mono text-sm">{current.slug}</code>
              <CopyButton value={current.slug} label={tc("copy")} />
            </div>
          </Field>
          <Field label={t("region")} hint={t("regionHint")}>
            <Select
              value={region}
              onValueChange={setRegion}
              disabled={!isAdmin}
              options={regions.map((r) => ({ value: r.id, label: r.name === r.id ? r.id : `${r.name} (${r.id})` }))}
            />
          </Field>
          <Field label={t("residency")}>
            <div className="flex h-8 items-center gap-2">
              <Badge tone={current.data_residency === "eu_strict" ? "accent" : "neutral"}>
                {current.data_residency === "eu_strict" ? t("euStrict") : t("standard")}
              </Badge>
              <Link href="/app/settings/residency" className="text-sm text-fg-muted underline underline-offset-4 hover:text-fg">
                {t("residencyLink")}
              </Link>
            </div>
          </Field>
        </CardBody>
        {isAdmin ? (
          <CardFooter>
            <Button variant="primary" disabled={!dirty || !name.trim()} loading={save.isPending} onClick={() => save.mutate()}>
              {tc("save")}
            </Button>
          </CardFooter>
        ) : null}
      </Card>

      <Card id="danger" className="border-danger/30">
        <CardHeader title={t("danger")} />
        <CardBody className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="max-w-xl">
            <p className="text-sm font-medium">{t("deleteTitle")}</p>
            <p className="mt-0.5 text-sm text-fg-muted">{t("deleteDescription")}</p>
            {!isOwner ? <p className="mt-1 text-xs text-fg-subtle">{t("ownerOnly")}</p> : null}
          </div>
          <Button
            variant="danger"
            disabled={!isOwner || deletion !== null}
            onClick={() => {
              setDeleteError(null);
              setDeleteOpen(true);
            }}
          >
            <Trash2 />
            {t("delete")}
          </Button>
        </CardBody>
      </Card>

      <TypedConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={t("deleteConfirmTitle", { name: current.name })}
        description={t("deleteDescription")}
        expected={current.slug}
        confirmLabel={t("delete")}
        loading={remove.isPending}
        error={deleteError}
        onConfirm={(typed) => remove.mutate(typed)}
      />
    </div>
  );
}

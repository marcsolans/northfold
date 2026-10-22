"use client";

import {
  Alert,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  PageHeader,
  Select,
  SkeletonRows,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Download, FileArchive, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { DataRequestsTable } from "@/components/enterprise/data-requests-table";
import { TypedConfirmDialog } from "@/components/enterprise/typed-confirm-dialog";
import type { DataRequest, Member } from "@/components/enterprise/types";
import { ApiError, http } from "@/lib/api";
import { useMe, useRole } from "@/lib/hooks/use-me";

type NewRequest = { kind: "export" | "delete"; scope: "user" | "org"; subject_user_id?: string; confirm?: string };

const active = (rows: DataRequest[] | undefined) => (rows ?? []).some((r) => r.status === "pending" || r.status === "running");

export default function DataSettingsPage() {
  const t = useTranslations("enterprise.data");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const router = useRouter();
  const { data: me } = useMe();
  const isAdmin = useRole("admin");

  const mine = useQuery({
    queryKey: ["data-requests", "mine"],
    queryFn: () => http.get<DataRequest[]>("/data-requests/mine"),
    refetchInterval: (q) => (active(q.state.data) ? 4000 : false),
  });
  const all = useQuery({
    queryKey: ["data-requests", "org"],
    queryFn: () => http.get<DataRequest[]>("/data-requests"),
    enabled: isAdmin,
    refetchInterval: (q) => (active(q.state.data) ? 4000 : false),
  });
  const members = useQuery({ queryKey: ["members"], queryFn: () => http.get<Member[]>("/members"), enabled: isAdmin });

  const [subject, setSubject] = React.useState<string>("");
  const [confirming, setConfirming] = React.useState<"self" | "member" | null>(null);
  const [confirmError, setConfirmError] = React.useState<string | null>(null);

  const create = useMutation({
    mutationFn: (body: NewRequest) => http.post<DataRequest>("/data-requests", body),
    onSuccess: (req) => {
      setConfirming(null);
      toast.success(t("requested"));
      void qc.invalidateQueries({ queryKey: ["data-requests"] });
      if (req.kind === "delete" && req.scope === "user" && req.subject?.id === me?.id) router.refresh();
    },
    onError: (err) => {
      const message = err instanceof ApiError ? err.message : String(err);
      if (confirming) setConfirmError(message);
      else toast.error(message);
    },
  });

  const others = (members.data ?? []).filter((m) => m.user_id !== me?.id);
  const selected = others.find((m) => m.user_id === subject);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ts("data")} description={t("description")} />

      <Card>
        <CardHeader title={t("mine")} description={t("mineDescription")} />
        <CardBody className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              loading={create.isPending && create.variables?.kind === "export" && create.variables.scope === "user" && !create.variables.subject_user_id}
              onClick={() => create.mutate({ kind: "export", scope: "user" })}
            >
              <Download />
              {t("exportMine")}
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                setConfirmError(null);
                setConfirming("self");
              }}
            >
              <Trash2 />
              {t("deleteMine")}
            </Button>
          </div>
          {mine.isLoading ? (
            <SkeletonRows rows={2} />
          ) : mine.error ? (
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void mine.refetch()} />
          ) : (mine.data ?? []).length > 0 ? (
            <DataRequestsTable requests={mine.data ?? []} currentUserId={me?.id} canDownloadOrgReach={false} showSubject={false} />
          ) : null}
        </CardBody>
      </Card>

      {isAdmin ? (
        <>
          <Card>
            <CardHeader title={t("member")} description={t("memberDescription")} />
            <CardBody className="flex flex-wrap items-end gap-3">
              <Field label={t("memberSelect")} className="w-full max-w-sm">
                <Select
                  value={subject || undefined}
                  onValueChange={setSubject}
                  placeholder={members.isLoading ? tc("loading") : t("memberPlaceholder")}
                  options={others.map((m) => ({ value: m.user_id, label: m.name ? `${m.name} · ${m.email}` : m.email }))}
                />
              </Field>
              <Button
                variant="secondary"
                disabled={!subject}
                loading={create.isPending && create.variables?.subject_user_id === subject && create.variables.kind === "export"}
                onClick={() => create.mutate({ kind: "export", scope: "user", subject_user_id: subject })}
              >
                <Download />
                {t("exportMember")}
              </Button>
              <Button
                variant="danger"
                disabled={!subject}
                onClick={() => {
                  setConfirmError(null);
                  setConfirming("member");
                }}
              >
                <Trash2 />
                {t("deleteMember")}
              </Button>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={t("org")} description={t("orgDescription")} />
            <CardBody className="flex flex-wrap items-center gap-3">
              <Button
                variant="secondary"
                loading={create.isPending && create.variables?.scope === "org"}
                onClick={() => create.mutate({ kind: "export", scope: "org" })}
              >
                <FileArchive />
                {t("exportOrg")}
              </Button>
              <Button asChild variant="ghost">
                <Link href="/app/settings/organization#danger">
                  <Building2 />
                  {t("deleteOrgLink")}
                </Link>
              </Button>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={t("requests")} description={t("requestsDescription")} />
            {all.isLoading ? (
              <div className="p-4">
                <SkeletonRows rows={3} />
              </div>
            ) : all.error ? (
              <div className="p-4">
                <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void all.refetch()} />
              </div>
            ) : (all.data ?? []).length === 0 ? (
              <div className="p-4">
                <EmptyState icon={<FileArchive />} title={t("empty")} description={t("emptyDescription")} />
              </div>
            ) : (
              <DataRequestsTable requests={all.data ?? []} currentUserId={me?.id} canDownloadOrgReach />
            )}
          </Card>
        </>
      ) : (
        <Alert tone="info">{t("adminHint")}</Alert>
      )}

      <TypedConfirmDialog
        open={confirming === "self"}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={t("deleteMineTitle")}
        description={t("deleteMineDescription")}
        expected={me?.email ?? ""}
        confirmLabel={t("deleteMine")}
        loading={create.isPending}
        error={confirmError}
        onConfirm={(typed) => create.mutate({ kind: "delete", scope: "user", confirm: typed })}
      />
      <TypedConfirmDialog
        open={confirming === "member" && selected !== undefined}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={t("deleteMemberTitle", { email: selected?.email ?? "" })}
        description={t("deleteMemberDescription")}
        expected={selected?.email ?? ""}
        confirmLabel={t("deleteMember")}
        loading={create.isPending}
        error={confirmError}
        onConfirm={(typed) => create.mutate({ kind: "delete", scope: "user", subject_user_id: subject, confirm: typed })}
      />
    </div>
  );
}

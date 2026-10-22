"use client";

import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Select,
  SkeletonRows,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Textarea,
  toast,
} from "@messer/ui";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogIn, Search, Users } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ImpersonateDialog, type ImpersonationTarget } from "@/components/admin/impersonate-dialog";
import { ADMIN_KEY, type AdminUser, type UserPage } from "@/components/admin/types";
import { errorText } from "@/components/billing";
import { http } from "@/lib/api";
import { formatDate, formatRelative, localeTag } from "@/lib/format";
import { useMe } from "@/lib/hooks/use-me";

const PAGE_SIZE = 50;

export default function AdminUsersPage() {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const { data: me } = useMe();
  const [q, setQ] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [status, setStatus] = React.useState("all");
  const [page, setPage] = React.useState(0);
  const [impersonating, setImpersonating] = React.useState<ImpersonationTarget | null>(null);
  const [blocking, setBlocking] = React.useState<AdminUser | null>(null);
  const [reason, setReason] = React.useState("");

  React.useEffect(() => {
    const id = window.setTimeout(() => {
      setSearch(q.trim());
      setPage(0);
    }, 300);
    return () => window.clearTimeout(id);
  }, [q]);

  const users = useQuery({
    queryKey: [...ADMIN_KEY, "users", search, status, page],
    queryFn: () =>
      http.get<UserPage>("/admin/users", {
        q: search || undefined,
        status: status === "all" ? undefined : status,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  });
  const toggle = useMutation({
    mutationFn: (user: AdminUser) =>
      user.status === "blocked"
        ? http.post<AdminUser>(`/admin/users/${user.id}/unblock`)
        : http.post<AdminUser>(`/admin/users/${user.id}/block`, { reason: reason.trim() }),
    onSuccess: (user) => {
      toast.success(user.status === "blocked" ? t("users.blockedToast") : t("users.unblockedToast"));
      setBlocking(null);
      setReason("");
      void qc.invalidateQueries({ queryKey: ADMIN_KEY });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const total = users.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const isBlockedTarget = blocking?.status === "blocked";

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("users.title")} description={t("users.description")} />
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-fg-subtle" aria-hidden />
          <Input className="pl-8" placeholder={t("users.search")} aria-label={t("users.search")} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Select
          className="w-36"
          aria-label={tc("status")}
          value={status}
          onValueChange={(v) => {
            setStatus(v);
            setPage(0);
          }}
          options={[
            { value: "all", label: t("orgs.allStatuses") },
            { value: "active", label: t("users.active") },
            { value: "blocked", label: t("users.blocked") },
          ]}
        />
      </div>
      <Card>
        {users.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={8} />
          </div>
        ) : users.error || !users.data ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void users.refetch()} />
          </div>
        ) : users.data.items.length === 0 ? (
          <div className="p-4">
            <EmptyState icon={<Users />} title={t("users.emptyTitle")} description={t("users.empty")} />
          </div>
        ) : (
          <>
            <Table>
              <THead>
                <tr>
                  <TH>{t("users.user")}</TH>
                  <TH className="hidden md:table-cell">{t("users.orgs")}</TH>
                  <TH className="hidden lg:table-cell">{t("detail.lastLogin")}</TH>
                  <TH className="hidden lg:table-cell">{tc("created")}</TH>
                  <TH className="w-56" />
                </tr>
              </THead>
              <TBody>
                {users.data.items.map((u) => {
                  const self = u.id === me?.id;
                  return (
                    <TR key={u.id}>
                      <TD>
                        <span className="font-medium">{u.name ?? u.email}</span>
                        {u.is_superadmin ? <Badge tone="accent" className="ml-2">{t("users.superadmin")}</Badge> : null}
                        {u.status === "blocked" ? <Badge tone="danger" className="ml-2">{t("users.blocked")}</Badge> : null}
                        <span className="block text-xs text-fg-subtle">{u.email}</span>
                      </TD>
                      <TD className="hidden md:table-cell">
                        {u.orgs.length === 0 ? (
                          <span className="text-fg-subtle">—</span>
                        ) : (
                          <span className="flex flex-col">
                            {u.orgs.slice(0, 3).map((o) => (
                              <Link key={o.id} href={`/admin/orgs/${o.id}`} className="text-sm hover:underline">
                                {o.name} <span className="text-xs text-fg-subtle">· {tc(`roles.${o.role}`)}</span>
                              </Link>
                            ))}
                            {u.orgs.length > 3 ? (
                              <span className="text-xs text-fg-subtle">{t("users.more", { count: u.orgs.length - 3 })}</span>
                            ) : null}
                          </span>
                        )}
                      </TD>
                      <TD className="hidden text-fg-muted lg:table-cell">
                        {u.last_login_at ? formatRelative(u.last_login_at, locale) : t("orgs.never")}
                      </TD>
                      <TD className="hidden text-fg-muted lg:table-cell">{formatDate(u.created_at, locale)}</TD>
                      <TD className="text-right">
                        {!u.is_superadmin && !self ? (
                          <div className="flex justify-end gap-1">
                            {u.status !== "blocked" ? (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setImpersonating({ userId: u.id, email: u.email, orgs: u.orgs })}
                              >
                                <LogIn />
                                {t("users.impersonate")}
                              </Button>
                            ) : null}
                            <Button size="sm" variant="ghost" onClick={() => setBlocking(u)}>
                              {u.status === "blocked" ? t("users.unblock") : t("users.block")}
                            </Button>
                          </div>
                        ) : null}
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
            <div className="flex items-center justify-between border-t border-border px-4 py-2 text-sm text-fg-muted">
              <span>{t("users.pageOf", { page: page + 1, pages, total })}</span>
              <div className="flex gap-2">
                <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
                  {t("common.previous")}
                </Button>
                <Button size="sm" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
                  {t("common.next")}
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>

      <ImpersonateDialog target={impersonating} onClose={() => setImpersonating(null)} />
      <ConfirmDialog
        open={blocking !== null}
        onOpenChange={(open) => {
          if (!open) {
            setBlocking(null);
            setReason("");
          }
        }}
        title={
          isBlockedTarget
            ? t("users.unblockTitle", { email: blocking?.email ?? "" })
            : t("users.blockTitle", { email: blocking?.email ?? "" })
        }
        description={isBlockedTarget ? t("users.unblockDescription") : t("users.blockDescription")}
        confirmLabel={isBlockedTarget ? t("users.unblock") : t("users.block")}
        cancelLabel={tc("cancel")}
        destructive={!isBlockedTarget}
        loading={toggle.isPending}
        onConfirm={() => {
          if (!blocking) return;
          if (!isBlockedTarget && reason.trim().length < 3) {
            toast.error(t("detail.reasonRequired"));
            return;
          }
          toggle.mutate(blocking);
        }}
      >
        {!isBlockedTarget ? (
          <Field label={t("detail.reason")} htmlFor="user-block-reason">
            <Textarea id="user-block-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}

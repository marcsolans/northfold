"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  Dialog,
  DialogContent,
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
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";
import { useMe } from "@/lib/hooks/use-me";
import { type Role, hasRole } from "@/lib/types";

interface Member {
  user_id: string;
  email: string;
  name: string | null;
  role: Role;
  source: "manual" | "sso" | "scim";
  joined_at: string;
}

interface Invitation {
  id: string;
  email: string;
  role: Role;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

const ROLES: Role[] = ["owner", "admin", "builder", "viewer"];

export default function MembersPage() {
  const t = useTranslations("settings.members");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const qc = useQueryClient();
  const { data: me } = useMe();
  const isAdmin = hasRole(me, "admin");
  const isOwner = hasRole(me, "owner");

  const members = useQuery({ queryKey: ["members"], queryFn: () => http.get<Member[]>("/members") });
  const invitations = useQuery({
    queryKey: ["invitations"],
    queryFn: () => http.get<Invitation[]>("/invitations"),
    enabled: isAdmin,
  });

  const [inviteOpen, setInviteOpen] = React.useState(false);
  const [inviteRole, setInviteRole] = React.useState<Role>("viewer");
  const [inviteError, setInviteError] = React.useState<string | null>(null);
  const [removing, setRemoving] = React.useState<Member | null>(null);
  const [revoking, setRevoking] = React.useState<Invitation | null>(null);

  const invite = useMutation({
    mutationFn: (body: { email: string; role: Role }) => http.post<Invitation>("/invitations", body),
    onSuccess: (inv) => {
      toast.success(t("inviteSent", { email: inv.email }));
      setInviteOpen(false);
      void qc.invalidateQueries({ queryKey: ["invitations"] });
    },
    onError: (err) => setInviteError(err instanceof ApiError ? err.message : String(err)),
  });
  const changeRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) => http.patch(`/members/${userId}`, { role }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["members"] }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  const remove = useMutation({
    mutationFn: (userId: string) => http.del(`/members/${userId}`),
    onSuccess: () => {
      setRemoving(null);
      void qc.invalidateQueries({ queryKey: ["members"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => http.del(`/invitations/${id}`),
    onSuccess: () => {
      setRevoking(null);
      void qc.invalidateQueries({ queryKey: ["invitations"] });
    },
  });

  const roleOptions = ROLES.filter((r) => isOwner || r !== "owner").map((r) => ({
    value: r,
    label: tc(`roles.${r}`),
    description: t(`roleDescriptions.${r}`),
  }));
  const pending = (invitations.data ?? []).filter(
    (i) => !i.accepted_at && !i.revoked_at && new Date(i.expires_at).getTime() > Date.now(),
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={ts("members")}
        description={t("description")}
        actions={
          isAdmin ? (
            <Button
              variant="primary"
              onClick={() => {
                setInviteError(null);
                setInviteOpen(true);
              }}
            >
              <UserPlus />
              {t("invite")}
            </Button>
          ) : null
        }
      />

      <Card>
        {members.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={3} />
          </div>
        ) : members.error ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void members.refetch()} />
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{tc("name")}</TH>
                <TH>{tc("role")}</TH>
                <TH className="hidden sm:table-cell">{tc("created")}</TH>
                <TH className="w-24" />
              </tr>
            </THead>
            <TBody>
              {(members.data ?? []).map((m) => {
                const isMe = m.user_id === me?.id;
                const canEdit = isAdmin && !isMe && (isOwner || m.role !== "owner");
                return (
                  <TR key={m.user_id}>
                    <TD>
                      <div className="flex flex-col">
                        <span className="font-medium">
                          {m.name ?? m.email} {isMe ? <Badge className="ml-1">{t("you")}</Badge> : null}
                        </span>
                        <span className="text-xs text-fg-subtle">{m.email}</span>
                      </div>
                    </TD>
                    <TD className="w-56">
                      {canEdit ? (
                        <Select
                          aria-label={tc("role")}
                          value={m.role}
                          onValueChange={(role) => changeRole.mutate({ userId: m.user_id, role: role as Role })}
                          options={roleOptions}
                        />
                      ) : (
                        <span className="flex items-center gap-2">
                          {tc(`roles.${m.role}`)}
                          {m.source !== "manual" ? <Badge tone="info">{t(`source.${m.source}`)}</Badge> : null}
                        </span>
                      )}
                    </TD>
                    <TD className="hidden text-fg-muted sm:table-cell">{formatDate(m.joined_at, locale)}</TD>
                    <TD className="text-right">
                      {canEdit ? (
                        <Button variant="ghost" size="sm" onClick={() => setRemoving(m)}>
                          {tc("remove")}
                        </Button>
                      ) : null}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>

      {isAdmin ? (
        <Card>
          <CardHeader title={t("pending")} />
          {invitations.isLoading ? (
            <div className="p-4">
              <SkeletonRows rows={2} />
            </div>
          ) : pending.length === 0 ? (
            <p className="p-4 text-sm text-fg-subtle">{t("noPending")}</p>
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{tc("email")}</TH>
                  <TH>{tc("role")}</TH>
                  <TH>{t("expires")}</TH>
                  <TH className="w-24" />
                </tr>
              </THead>
              <TBody>
                {pending.map((inv) => (
                  <TR key={inv.id}>
                    <TD>{inv.email}</TD>
                    <TD>{tc(`roles.${inv.role}`)}</TD>
                    <TD className="text-fg-muted">{formatDate(inv.expires_at, locale)}</TD>
                    <TD className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => setRevoking(inv)}>
                        {t("revoke")}
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      ) : null}

      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent title={t("inviteTitle")} description={t("inviteDescription")}>
          <form
            id="invite-form"
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              setInviteError(null);
              invite.mutate({ email: String(new FormData(e.currentTarget).get("email")), role: inviteRole });
            }}
          >
            {inviteError ? <Alert tone="danger">{inviteError}</Alert> : null}
            <Field label={tc("email")} htmlFor="invite-email">
              <Input id="invite-email" name="email" type="email" required autoFocus />
            </Field>
            <Field label={tc("role")}>
              <Select value={inviteRole} onValueChange={(v) => setInviteRole(v as Role)} options={roleOptions} />
            </Field>
            <div className="mt-2 flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setInviteOpen(false)}>
                {tc("cancel")}
              </Button>
              <Button type="submit" variant="primary" loading={invite.isPending}>
                {t("invite")}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("removeConfirm", { email: removing?.email ?? "" })}
        description={t("removeDescription")}
        confirmLabel={tc("remove")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.user_id);
        }}
      />
      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => !open && setRevoking(null)}
        title={t("revokeConfirm", { email: revoking?.email ?? "" })}
        confirmLabel={t("revoke")}
        cancelLabel={tc("cancel")}
        loading={revoke.isPending}
        onConfirm={() => {
          if (revoking) revoke.mutate(revoking.id);
        }}
      />
    </div>
  );
}

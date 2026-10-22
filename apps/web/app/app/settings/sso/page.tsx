"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  CopyButton,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  SkeletonRows,
  Switch,
  toast,
} from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, ChevronDown, ChevronRight, FlaskConical, Pencil, Plus, ShieldCheck, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { billingHref } from "@/components/billing";
import { ScimCard } from "@/components/enterprise/scim-card";
import { SsoConnectionDialog } from "@/components/enterprise/sso-connection-dialog";
import { SsoDomainsCard } from "@/components/enterprise/sso-domains-card";
import { SsoMappingsSheet } from "@/components/enterprise/sso-mappings-sheet";
import { SsoTestResultDialog } from "@/components/enterprise/sso-test-result-dialog";
import type { SsoConnection, SsoOverview, SsoPresets } from "@/components/enterprise/types";
import { ApiError, http } from "@/lib/api";
import { useMe, useRole } from "@/lib/hooks/use-me";

export default function SsoSettingsPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <SsoSettings />
    </React.Suspense>
  );
}

function SsoSettings() {
  const t = useTranslations("enterprise");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const me = useMe();
  const isAdmin = useRole("admin");
  const qc = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const testKey = params.get("test_result");

  const overview = useQuery({
    queryKey: ["sso", "overview"],
    queryFn: () => http.get<SsoOverview>("/sso/overview"),
    enabled: isAdmin,
  });
  const presets = useQuery({
    queryKey: ["sso", "presets"],
    queryFn: () => http.get<SsoPresets>("/sso/presets"),
    enabled: isAdmin,
    staleTime: 3_600_000,
  });
  const connections = useQuery({
    queryKey: ["sso", "connections"],
    queryFn: () => http.get<SsoConnection[]>("/sso/connections"),
    enabled: isAdmin,
  });

  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<SsoConnection | null>(null);
  const [mappingsFor, setMappingsFor] = React.useState<SsoConnection | null>(null);
  const [deleting, setDeleting] = React.useState<SsoConnection | null>(null);
  const [expanded, setExpanded] = React.useState<string | null>(null);

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => http.patch(`/sso/connections/${id}`, { enabled }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sso", "connections"] }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => http.del(`/sso/connections/${id}`),
    onSuccess: () => {
      setDeleting(null);
      toast.success(t("sso.deleted"));
      void qc.invalidateQueries({ queryKey: ["sso"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });

  if (me.isLoading) return <Skeleton className="h-64 w-full" />;
  if (!isAdmin) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title={ts("sso")} description={t("sso.description")} />
        <Alert tone="info">{t("adminOnly")}</Alert>
      </div>
    );
  }

  const ov = overview.data;
  const startTest = (c: SsoConnection) => {
    window.location.assign(`${c.login_url}?test=true&next=${encodeURIComponent("/app/settings/sso")}`);
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={ts("sso")}
        description={t("sso.description")}
        actions={
          ov?.sso_available ? (
            <Button
              variant="primary"
              onClick={() => {
                setEditing(null);
                setDialogOpen(true);
              }}
            >
              <Plus />
              {t("sso.newConnection")}
            </Button>
          ) : null
        }
      />

      {overview.error ? (
        <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void overview.refetch()} />
      ) : null}
      {ov && !ov.sso_available ? (
        <Alert
          tone="warning"
          title={t("upgrade.title")}
          action={
            <Button asChild size="sm" variant="dark">
              <Link href={billingHref(ov.sso_upgrade_to)}>
                {t("upgrade.seePlans")}
                <ArrowUpRight />
              </Link>
            </Button>
          }
        >
          {t("upgrade.sso")}
        </Alert>
      ) : null}

      <SsoDomainsCard />

      <Card>
        <CardHeader title={t("sso.connections")} description={t("sso.connectionsDescription")} />
        {connections.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={3} />
          </div>
        ) : connections.error ? (
          <div className="p-4">
            <ErrorState title={tc("errorTitle")} description={tc("errorGeneric")} onRetry={() => void connections.refetch()} />
          </div>
        ) : (connections.data ?? []).length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<ShieldCheck />}
              title={t("sso.empty")}
              description={t("sso.emptyDescription")}
              action={
                ov?.sso_available ? (
                  <Button
                    variant="primary"
                    onClick={() => {
                      setEditing(null);
                      setDialogOpen(true);
                    }}
                  >
                    <Plus />
                    {t("sso.newConnection")}
                  </Button>
                ) : null
              }
            />
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {(connections.data ?? []).map((c) => {
              const open = expanded === c.id;
              const expiredCert = c.config.certificates?.some((cert) => cert.expired);
              return (
                <li key={c.id} className="px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <button
                      type="button"
                      className="flex min-w-0 items-center gap-2 text-left"
                      aria-expanded={open}
                      onClick={() => setExpanded(open ? null : c.id)}
                    >
                      {open ? <ChevronDown className="size-4 text-fg-subtle" /> : <ChevronRight className="size-4 text-fg-subtle" />}
                      <span className="min-w-0">
                        <span className="flex flex-wrap items-center gap-1.5 font-medium">
                          {c.name}
                          <Badge tone="outline">{c.type === "oidc" ? "OIDC" : "SAML"}</Badge>
                          {c.config.preset ? <Badge>{t(`presets.${c.config.preset}`)}</Badge> : null}
                          {c.enforce ? <Badge tone="accent">{t("sso.enforced")}</Badge> : null}
                          {!c.enabled ? <Badge tone="neutral">{t("sso.disabled")}</Badge> : null}
                          {expiredCert ? <Badge tone="danger">{t("sso.samlFields.expired")}</Badge> : null}
                        </span>
                        <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
                          {c.domain}
                          {c.domain_verified ? (
                            <Badge tone="success">{t("sso.verified")}</Badge>
                          ) : (
                            <Badge tone="warning">{t("sso.unverified")}</Badge>
                          )}
                          · {t("sso.defaultRoleShort", { role: tc(`roles.${c.default_role}`) })}
                          · {t("sso.mappingCount", { count: c.mappings })}
                        </span>
                      </span>
                    </button>
                    <div className="flex items-center gap-1">
                      <Switch
                        aria-label={t("sso.enabled")}
                        checked={c.enabled}
                        disabled={toggle.isPending}
                        onCheckedChange={(enabled) => toggle.mutate({ id: c.id, enabled })}
                      />
                      <Button variant="ghost" size="sm" onClick={() => startTest(c)} title={t("sso.testHint")}>
                        <FlaskConical />
                        {t("sso.test")}
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setMappingsFor(c)}>
                        <Users />
                        {t("sso.mappings")}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={tc("edit")}
                        onClick={() => {
                          setEditing(c);
                          setDialogOpen(true);
                        }}
                      >
                        <Pencil />
                      </Button>
                      <Button variant="ghost" size="icon-sm" aria-label={tc("delete")} onClick={() => setDeleting(c)}>
                        <Trash2 />
                      </Button>
                    </div>
                  </div>
                  {open ? (
                    <div className="mt-3 rounded-md border border-border bg-subtle p-3">
                      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-subtle">{t("sso.spTitle")}</p>
                      <dl className="grid gap-2 text-xs sm:grid-cols-[10rem_1fr]">
                        {Object.entries(c.service_provider).map(([key, value]) => (
                          <React.Fragment key={key}>
                            <dt className="text-fg-muted">{t(`sso.sp.${key}`)}</dt>
                            <dd className="flex min-w-0 items-center gap-1">
                              <code className="min-w-0 break-all font-mono">{value}</code>
                              <CopyButton value={value} label={tc("copy")} />
                            </dd>
                          </React.Fragment>
                        ))}
                      </dl>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {ov ? <ScimCard overview={ov} /> : null}

      <SsoConnectionDialog open={dialogOpen} onOpenChange={setDialogOpen} connection={editing} presets={presets.data} />
      <SsoMappingsSheet connection={mappingsFor} onOpenChange={(open) => !open && setMappingsFor(null)} />
      <SsoTestResultDialog resultKey={testKey} onClose={() => router.replace(pathname)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("sso.deleteConfirm", { name: deleting?.name ?? "" })}
        description={t("sso.deleteDescription")}
        confirmLabel={tc("delete")}
        cancelLabel={tc("cancel")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id);
        }}
      />
    </div>
  );
}

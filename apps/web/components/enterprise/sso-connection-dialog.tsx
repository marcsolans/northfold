"use client";

import {
  Alert,
  Button,
  Dialog,
  DialogContent,
  Field,
  Input,
  RadioCards,
  Select,
  Switch,
  Textarea,
  toast,
} from "@messer/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";

import { PlanLimitNotice, isPlanLimitError } from "@/components/billing";
import { ApiError, http } from "@/lib/api";

import {
  ASSIGNABLE_ROLES,
  type AssignableRole,
  PRESET_KEYS,
  type PresetKey,
  type SsoConnection,
  type SsoPresets,
  type SsoType,
} from "./types";

type FormKey =
  | "name"
  | "domain"
  | "issuer"
  | "client_id"
  | "client_secret"
  | "scopes"
  | "groups_claim"
  | "email_claim"
  | "metadata_xml"
  | "idp_entity_id"
  | "idp_sso_url"
  | "certificate"
  | "email_attribute"
  | "first_name_attribute"
  | "last_name_attribute"
  | "groups_attribute"
  | "name_id_format";

type FormState = Record<FormKey, string>;

const EMPTY: FormState = {
  name: "",
  domain: "",
  issuer: "",
  client_id: "",
  client_secret: "",
  scopes: "openid email profile",
  groups_claim: "groups",
  email_claim: "email",
  metadata_xml: "",
  idp_entity_id: "",
  idp_sso_url: "",
  certificate: "",
  email_attribute: "",
  first_name_attribute: "",
  last_name_attribute: "",
  groups_attribute: "",
  name_id_format: "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
};

const TEXT_KEYS: FormKey[] = [
  "issuer",
  "groups_claim",
  "email_claim",
  "idp_entity_id",
  "idp_sso_url",
  "email_attribute",
  "first_name_attribute",
  "last_name_attribute",
  "groups_attribute",
  "name_id_format",
];

function str(value: unknown): string {
  if (Array.isArray(value)) return value.join(" ");
  return typeof value === "string" ? value : "";
}

/** Values of a preset: concrete ones fill the form, templated ones ("{tenant_id}") become placeholders. */
function presetValues(presets: SsoPresets | undefined, preset: PresetKey, type: SsoType) {
  const raw = presets?.presets[preset]?.[type] ?? {};
  const values: Partial<FormState> = {};
  const placeholders: Partial<FormState> = {};
  for (const [key, value] of Object.entries(raw)) {
    const text = str(value);
    const formKey = (key === "scopes" ? "scopes" : key) as FormKey;
    if (!(formKey in EMPTY)) continue;
    if (text.includes("{")) placeholders[formKey] = text;
    else values[formKey] = text;
  }
  return { values, placeholders };
}

export function SsoConnectionDialog({
  open,
  onOpenChange,
  connection,
  presets,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connection: SsoConnection | null;
  presets: SsoPresets | undefined;
}) {
  const t = useTranslations("enterprise");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const editing = connection !== null;
  const [type, setType] = React.useState<SsoType>("oidc");
  const [preset, setPreset] = React.useState<PresetKey>("entra");
  const [form, setForm] = React.useState<FormState>(EMPTY);
  const [placeholders, setPlaceholders] = React.useState<Partial<FormState>>({});
  const [defaultRole, setDefaultRole] = React.useState<AssignableRole>("viewer");
  const [enabled, setEnabled] = React.useState(true);
  const [enforce, setEnforce] = React.useState(false);
  const [jit, setJit] = React.useState(true);
  const [allowIdpInitiated, setAllowIdpInitiated] = React.useState(false);
  const [requireAssertionSignature, setRequireAssertionSignature] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  React.useEffect(() => {
    if (!open) return;
    setError(null);
    if (connection) {
      const c = connection.config;
      const next: FormState = { ...EMPTY, name: connection.name, domain: connection.domain };
      for (const key of TEXT_KEYS) next[key] = str(c[key]);
      next.client_id = str(c.client_id);
      next.scopes = str(c.scopes) || EMPTY.scopes;
      setType(connection.type);
      setPreset(c.preset ?? "generic");
      setForm(next);
      setPlaceholders({});
      setDefaultRole(connection.default_role);
      setEnabled(connection.enabled);
      setEnforce(connection.enforce);
      setJit(c.jit_provisioning !== false);
      setAllowIdpInitiated(c.allow_idp_initiated === true);
      setRequireAssertionSignature(c.require_assertion_signature === true);
    } else {
      setType("oidc");
      setPreset("entra");
      const { values, placeholders: ph } = presetValues(presets, "entra", "oidc");
      setForm({ ...EMPTY, ...values });
      setPlaceholders(ph);
      setDefaultRole("viewer");
      setEnabled(true);
      setEnforce(false);
      setJit(true);
      setAllowIdpInitiated(false);
      setRequireAssertionSignature(false);
    }
  }, [open, connection, presets]);

  const applyPreset = (nextPreset: PresetKey, nextType: SsoType) => {
    setPreset(nextPreset);
    setType(nextType);
    const { values, placeholders: ph } = presetValues(presets, nextPreset, nextType);
    setForm((f) => ({ ...EMPTY, name: f.name, domain: f.domain, ...values }));
    setPlaceholders(ph);
  };

  const set = (key: FormKey) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const save = useMutation({
    mutationFn: () => {
      const config: Record<string, unknown> = { preset, jit_provisioning: jit };
      if (type === "oidc") {
        config.issuer = form.issuer.trim();
        config.client_id = form.client_id.trim();
        if (form.client_secret) config.client_secret = form.client_secret;
        config.scopes = form.scopes.split(/[\s,]+/).filter(Boolean);
        config.groups_claim = form.groups_claim.trim();
        config.email_claim = form.email_claim.trim() || "email";
      } else {
        if (form.metadata_xml.trim()) config.metadata_xml = form.metadata_xml;
        if (form.idp_entity_id.trim()) config.idp_entity_id = form.idp_entity_id.trim();
        if (form.idp_sso_url.trim()) config.idp_sso_url = form.idp_sso_url.trim();
        if (form.certificate.trim()) config.idp_certificates = [form.certificate.trim()];
        config.email_attribute = form.email_attribute.trim() || null;
        config.first_name_attribute = form.first_name_attribute.trim() || null;
        config.last_name_attribute = form.last_name_attribute.trim() || null;
        config.groups_attribute = form.groups_attribute.trim() || null;
        config.name_id_format = form.name_id_format;
        config.allow_idp_initiated = allowIdpInitiated;
        config.require_assertion_signature = requireAssertionSignature;
      }
      const body = {
        name: form.name.trim(),
        domain: form.domain.trim(),
        default_role: defaultRole,
        enabled,
        enforce,
        config,
      };
      return editing
        ? http.patch<SsoConnection>(`/sso/connections/${connection.id}`, body)
        : http.post<SsoConnection>("/sso/connections", { ...body, type });
    },
    onSuccess: () => {
      toast.success(editing ? t("sso.updated") : t("sso.created"));
      void qc.invalidateQueries({ queryKey: ["sso"] });
      onOpenChange(false);
    },
    onError: (err) => setError(err),
  });

  const ph = (key: FormKey) => placeholders[key];
  const presetOptions = PRESET_KEYS.map((key) => ({ value: key, label: t(`presets.${key}`) }));
  const roleOptions = ASSIGNABLE_ROLES.map((r) => ({ value: r, label: tc(`roles.${r}`) }));
  const nameIdOptions = (presets?.name_id_formats ?? [EMPTY.name_id_format]).map((f) => ({
    value: f,
    label: f.split(":").pop() ?? f,
  }));
  const placeholderNames = presets?.presets[preset]?.placeholders ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        wide
        title={editing ? t("sso.editConnection") : t("sso.newConnection")}
        description={t("sso.dialogDescription")}
        footer={
          <>
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              {tc("cancel")}
            </Button>
            <Button type="submit" form="sso-connection-form" variant="primary" loading={save.isPending}>
              {editing ? tc("save") : tc("create")}
            </Button>
          </>
        }
      >
        <form
          id="sso-connection-form"
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            save.mutate();
          }}
        >
          {error && isPlanLimitError(error) ? <PlanLimitNotice error={error} /> : null}
          {error && !isPlanLimitError(error) ? (
            <Alert tone="danger">{error instanceof ApiError ? error.message : String(error)}</Alert>
          ) : null}

          {!editing ? (
            <Field label={t("sso.type")}>
              <RadioCards
                className="grid-cols-2"
                value={type}
                onValueChange={(v) => applyPreset(preset, v as SsoType)}
                options={[
                  { value: "oidc", label: t("sso.oidc"), description: t("sso.oidcDescription") },
                  { value: "saml", label: t("sso.saml"), description: t("sso.samlDescription") },
                ]}
              />
            </Field>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("sso.provider")}>
              <Select
                value={preset}
                onValueChange={(v) => (editing ? setPreset(v as PresetKey) : applyPreset(v as PresetKey, type))}
                options={presetOptions}
              />
            </Field>
            <Field label={t("sso.name")} htmlFor="sso-name">
              <Input id="sso-name" required maxLength={200} value={form.name} onChange={set("name")} />
            </Field>
            <Field label={t("sso.domain")} htmlFor="sso-domain" hint={t("sso.domainHint")}>
              <Input id="sso-domain" required placeholder="empresa.com" value={form.domain} onChange={set("domain")} />
            </Field>
            <Field label={t("sso.defaultRole")} hint={t("sso.defaultRoleHint")}>
              <Select value={defaultRole} onValueChange={(v) => setDefaultRole(v as AssignableRole)} options={roleOptions} />
            </Field>
          </div>

          {placeholderNames.length > 0 && !editing ? (
            <Alert tone="info">{t("sso.placeholderHint", { placeholders: placeholderNames.map((p) => `{${p}}`).join(", ") })}</Alert>
          ) : null}

          {type === "oidc" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("sso.oidcFields.issuer")} htmlFor="sso-issuer" hint={t("sso.oidcFields.issuerHint")} className="sm:col-span-2">
                <Input id="sso-issuer" required value={form.issuer} placeholder={ph("issuer")} onChange={set("issuer")} />
              </Field>
              <Field label={t("sso.oidcFields.clientId")} htmlFor="sso-client-id">
                <Input id="sso-client-id" required value={form.client_id} onChange={set("client_id")} autoComplete="off" />
              </Field>
              <Field
                label={t("sso.oidcFields.clientSecret")}
                htmlFor="sso-client-secret"
                hint={editing ? t("sso.oidcFields.clientSecretKeep") : undefined}
              >
                <Input
                  id="sso-client-secret"
                  type="password"
                  required={!editing}
                  value={form.client_secret}
                  onChange={set("client_secret")}
                  autoComplete="new-password"
                />
              </Field>
              <Field label={t("sso.oidcFields.scopes")} htmlFor="sso-scopes">
                <Input id="sso-scopes" value={form.scopes} onChange={set("scopes")} />
              </Field>
              <Field label={t("sso.oidcFields.groupsClaim")} htmlFor="sso-groups-claim" hint={t("sso.oidcFields.groupsClaimHint")}>
                <Input id="sso-groups-claim" value={form.groups_claim} onChange={set("groups_claim")} />
              </Field>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("sso.samlFields.metadataXml")} htmlFor="sso-metadata" hint={t("sso.samlFields.metadataHint")} className="sm:col-span-2">
                <Textarea id="sso-metadata" rows={3} className="font-mono text-xs" value={form.metadata_xml} onChange={set("metadata_xml")} />
              </Field>
              <Field label={t("sso.samlFields.idpEntityId")} htmlFor="sso-idp-entity">
                <Input id="sso-idp-entity" value={form.idp_entity_id} placeholder={ph("idp_entity_id")} onChange={set("idp_entity_id")} />
              </Field>
              <Field label={t("sso.samlFields.idpSsoUrl")} htmlFor="sso-idp-url">
                <Input id="sso-idp-url" value={form.idp_sso_url} placeholder={ph("idp_sso_url")} onChange={set("idp_sso_url")} />
              </Field>
              <Field
                label={t("sso.samlFields.certificate")}
                htmlFor="sso-cert"
                hint={editing ? t("sso.samlFields.certificateKeep") : undefined}
                className="sm:col-span-2"
              >
                <Textarea
                  id="sso-cert"
                  rows={3}
                  className="font-mono text-xs"
                  placeholder="-----BEGIN CERTIFICATE-----"
                  value={form.certificate}
                  onChange={set("certificate")}
                />
              </Field>
              {editing && connection?.config.certificates?.length ? (
                <div className="sm:col-span-2">
                  <p className="mb-1 text-sm font-medium">{t("sso.samlFields.currentCertificates")}</p>
                  <ul className="flex flex-col gap-1 text-xs text-fg-muted">
                    {connection.config.certificates.map((c) => (
                      <li key={c.fingerprint_sha256} className="font-mono">
                        {c.subject} · {c.expired ? t("sso.samlFields.expired") : t("sso.samlFields.expires", { date: c.not_after.slice(0, 10) })}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <Field label={t("sso.samlFields.emailAttribute")} htmlFor="sso-email-attr" hint={t("sso.samlFields.emailAttributeHint")}>
                <Input id="sso-email-attr" value={form.email_attribute} onChange={set("email_attribute")} />
              </Field>
              <Field label={t("sso.samlFields.groupsAttribute")} htmlFor="sso-groups-attr">
                <Input id="sso-groups-attr" value={form.groups_attribute} onChange={set("groups_attribute")} />
              </Field>
              <Field label={t("sso.samlFields.firstNameAttribute")} htmlFor="sso-first-attr">
                <Input id="sso-first-attr" value={form.first_name_attribute} onChange={set("first_name_attribute")} />
              </Field>
              <Field label={t("sso.samlFields.lastNameAttribute")} htmlFor="sso-last-attr">
                <Input id="sso-last-attr" value={form.last_name_attribute} onChange={set("last_name_attribute")} />
              </Field>
              <Field label={t("sso.samlFields.nameIdFormat")}>
                <Select value={form.name_id_format} onValueChange={(v) => setForm((f) => ({ ...f, name_id_format: v }))} options={nameIdOptions} />
              </Field>
              <div className="flex flex-col gap-3 pt-1">
                <ToggleRow label={t("sso.samlFields.allowIdpInitiated")} checked={allowIdpInitiated} onChange={setAllowIdpInitiated} />
                <ToggleRow
                  label={t("sso.samlFields.requireAssertionSignature")}
                  checked={requireAssertionSignature}
                  onChange={setRequireAssertionSignature}
                />
              </div>
            </div>
          )}

          <div className="flex flex-col gap-3 rounded-md border border-border p-3">
            <ToggleRow label={t("sso.enabled")} checked={enabled} onChange={setEnabled} />
            <ToggleRow label={t("sso.jit")} hint={t("sso.jitHint")} checked={jit} onChange={setJit} />
            <ToggleRow label={t("sso.enforce")} hint={t("sso.enforceHint")} checked={enforce} onChange={setEnforce} />
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ToggleRow({
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  const id = React.useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <label htmlFor={id} className="min-w-0 text-sm">
        <span className="font-medium text-fg">{label}</span>
        {hint ? <span className="block text-xs text-fg-muted">{hint}</span> : null}
      </label>
      <Switch id={id} checked={checked} onCheckedChange={onChange} disabled={disabled} />
    </div>
  );
}

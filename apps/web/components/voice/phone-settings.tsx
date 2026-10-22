"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Label,
  RadioCards,
  Select,
  SkeletonRows,
  Switch,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  Textarea,
  toast,
} from "@messer/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Phone, PhoneOutgoing, Plus, Search, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { useRole } from "@/lib/hooks/use-me";
import { errorMessage, useMembers } from "@/lib/studio/hooks";

import { usePhoneNumbers, useVoiceStatus, voiceKeys } from "./api";
import { VoiceCallsList } from "./calls-list";
import type { PhoneNumber, PhoneProvider, ProviderNumber, VoiceEnvironment } from "./types";

const E164 = /^\+[1-9]\d{6,14}$/;

function normalize(value: string): string {
  const raw = value.replace(/[^\d+]/g, "");
  return raw.startsWith("00") ? `+${raw.slice(2)}` : raw;
}

function useAgents(projectId: string) {
  const members = useMembers(projectId, "agent");
  return { ...members, names: (members.data ?? []).map((m) => m.name) };
}

function AssignNumberDialog({
  projectId,
  providers,
  open,
  onOpenChange,
}: {
  projectId: string;
  providers: PhoneProvider[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("voice.phone");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const agents = useAgents(projectId);
  const [provider, setProvider] = React.useState<PhoneProvider>(providers[0] ?? "twilio");
  const [source, setSource] = React.useState<"owned" | "buy">("owned");
  const [country, setCountry] = React.useState("ES");
  const [contains, setContains] = React.useState("");
  const [search, setSearch] = React.useState<{ country: string; contains: string } | null>(null);
  const [number, setNumber] = React.useState<ProviderNumber | null>(null);
  const [workforce, setWorkforce] = React.useState("");
  const [environment, setEnvironment] = React.useState<VoiceEnvironment>("production");
  const [label, setLabel] = React.useState("");
  const [recordCalls, setRecordCalls] = React.useState(false);
  const [greeting, setGreeting] = React.useState("");
  const [saving, setSaving] = React.useState(false);

  const owned = useQuery({
    queryKey: ["voice", "owned", provider],
    queryFn: () => http.get<ProviderNumber[]>("/voice/numbers/owned", { provider }),
    enabled: open && source === "owned",
  });
  const available = useQuery({
    queryKey: ["voice", "available", provider, search],
    queryFn: () =>
      http.get<ProviderNumber[]>("/voice/numbers/available", {
        provider,
        country: search?.country ?? "ES",
        contains: search?.contains || undefined,
      }),
    enabled: open && source === "buy" && search !== null,
  });

  React.useEffect(() => {
    if (!workforce && agents.names[0]) setWorkforce(agents.names[0]);
  }, [agents.names, workforce]);

  const candidates = (source === "owned" ? owned.data?.filter((n) => !n.assigned) : available.data) ?? [];
  const list = source === "owned" ? owned : available;

  const submit = async () => {
    if (!number || !workforce) return;
    setSaving(true);
    try {
      await http.post<PhoneNumber>("/voice/numbers", {
        project_id: projectId,
        provider,
        number: number.number,
        external_id: number.external_id || null,
        buy: source === "buy",
        workforce,
        environment,
        label,
        record_calls: recordCalls,
        greeting,
      });
      toast.success(source === "buy" ? t("bought", { number: number.number }) : t("assigned", { number: number.number }));
      void qc.invalidateQueries({ queryKey: voiceKeys.numbers(projectId) });
      onOpenChange(false);
      setNumber(null);
    } catch (err) {
      toast.error(errorMessage(err, tc("errorGeneric")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={t("assignTitle")}
        description={t("assignDescription")}
        wide
        footer={
          <>
            <Button variant="secondary" onClick={() => onOpenChange(false)}>
              {tc("cancel")}
            </Button>
            <Button variant="primary" onClick={() => void submit()} loading={saving} disabled={!number || !workforce}>
              {source === "buy" && number ? t("buyNumber", { number: number.number }) : t("assignNumber")}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("provider")}>
              <Select
                value={provider}
                onValueChange={(v) => {
                  setProvider(v as PhoneProvider);
                  setNumber(null);
                }}
                options={providers.map((p) => ({ value: p, label: t(`providers.${p}`) }))}
              />
            </Field>
            <Field label={t("agent")}>
              <Select
                value={workforce || undefined}
                onValueChange={setWorkforce}
                placeholder={agents.isLoading ? tc("loading") : t("pickAgent")}
                options={agents.names.map((n) => ({ value: n, label: n }))}
              />
            </Field>
          </div>
          <RadioCards
            value={source}
            onValueChange={(v) => {
              setSource(v as "owned" | "buy");
              setNumber(null);
            }}
            options={[
              { value: "owned", label: t("sourceOwned"), description: t("sourceOwnedHint") },
              { value: "buy", label: t("sourceBuy"), description: t("sourceBuyHint") },
            ]}
          />
          {source === "buy" ? (
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                setSearch({ country: country.toUpperCase(), contains: contains.replace(/\D/g, "") });
              }}
            >
              <Field label={t("country")} className="w-24">
                <Input value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} />
              </Field>
              <Field label={t("contains")} className="w-40">
                <Input value={contains} inputMode="numeric" onChange={(e) => setContains(e.target.value)} />
              </Field>
              <Button type="submit" variant="secondary">
                <Search />
                {tc("search")}
              </Button>
            </form>
          ) : null}
          {source === "buy" && search === null ? null : list.isLoading ? (
            <SkeletonRows rows={3} />
          ) : list.isError ? (
            <ErrorState title={tc("errorTitle")} description={errorMessage(list.error, tc("errorGeneric"))} onRetry={() => void list.refetch()} retryLabel={tc("retry")} />
          ) : candidates.length === 0 ? (
            <p className="text-sm text-fg-muted">{source === "owned" ? t("noOwned") : t("noAvailable")}</p>
          ) : (
            <div className="max-h-56 space-y-1 overflow-y-auto" role="radiogroup" aria-label={t("number")}>
              {candidates.map((n) => (
                <label
                  key={n.number}
                  className="flex cursor-pointer items-center gap-3 rounded-md border border-border px-3 py-2 text-sm has-[:checked]:border-fg"
                >
                  <input
                    type="radio"
                    name="voice-number"
                    className="accent-[var(--color-accent,#D52B1E)]"
                    checked={number?.number === n.number}
                    onChange={() => setNumber(n)}
                  />
                  <span className="tabular font-medium">{n.number}</span>
                  <span className="text-fg-muted">{[n.locality, n.country, n.label].filter(Boolean).join(" · ")}</span>
                </label>
              ))}
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("environment")} hint={t("environmentHint")}>
              <Select
                value={environment}
                onValueChange={(v) => setEnvironment(v as VoiceEnvironment)}
                options={[
                  { value: "production", label: t("production") },
                  { value: "development", label: t("development") },
                ]}
              />
            </Field>
            <Field label={t("label")}>
              <Input value={label} maxLength={200} onChange={(e) => setLabel(e.target.value)} placeholder={t("labelPlaceholder")} />
            </Field>
          </div>
          <Field label={t("greeting")} hint={t("greetingHint")}>
            <Textarea value={greeting} rows={2} maxLength={500} onChange={(e) => setGreeting(e.target.value)} />
          </Field>
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium">{t("recordCalls")}</p>
              <p className="text-xs text-fg-muted">{t("recordCallsHint")}</p>
            </div>
            <Switch checked={recordCalls} onCheckedChange={setRecordCalls} aria-label={t("recordCalls")} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function EditNumberDialog({
  projectId,
  number,
  onClose,
}: {
  projectId: string;
  number: PhoneNumber;
  onClose: () => void;
}) {
  const t = useTranslations("voice.phone");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const agents = useAgents(projectId);
  const [form, setForm] = React.useState({
    workforce: number.workforce_name,
    environment: number.environment,
    label: number.label,
    record_calls: number.record_calls,
    greeting: number.greeting,
  });
  const [saving, setSaving] = React.useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await http.patch<PhoneNumber>(`/voice/numbers/${number.id}`, form);
      toast.success(tc("saved"));
      void qc.invalidateQueries({ queryKey: voiceKeys.numbers(projectId) });
      onClose();
    } catch (err) {
      toast.error(errorMessage(err, tc("errorGeneric")));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open onOpenChange={(o) => (o ? null : onClose())}>
      <DialogContent
        title={t("editTitle", { number: number.number })}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              {tc("cancel")}
            </Button>
            <Button variant="primary" loading={saving} onClick={() => void save()}>
              {tc("save")}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label={t("agent")}>
            <Select
              value={form.workforce}
              onValueChange={(workforce) => setForm({ ...form, workforce })}
              options={agents.names.map((n) => ({ value: n, label: n }))}
            />
          </Field>
          <Field label={t("environment")}>
            <Select
              value={form.environment}
              onValueChange={(environment) => setForm({ ...form, environment: environment as VoiceEnvironment })}
              options={[
                { value: "production", label: t("production") },
                { value: "development", label: t("development") },
              ]}
            />
          </Field>
          <Field label={t("label")}>
            <Input value={form.label} maxLength={200} onChange={(e) => setForm({ ...form, label: e.target.value })} />
          </Field>
          <Field label={t("greeting")} hint={t("greetingHint")}>
            <Textarea value={form.greeting} rows={2} maxLength={500} onChange={(e) => setForm({ ...form, greeting: e.target.value })} />
          </Field>
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium">{t("recordCalls")}</p>
            <Switch checked={form.record_calls} onCheckedChange={(record_calls) => setForm({ ...form, record_calls })} aria-label={t("recordCalls")} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function OutboundCallDialog({ number, onClose }: { number: PhoneNumber; onClose: () => void }) {
  const t = useTranslations("voice.phone");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [to, setTo] = React.useState("");
  const [greeting, setGreeting] = React.useState("");
  const [calling, setCalling] = React.useState(false);
  const valid = E164.test(normalize(to));
  const call = async () => {
    setCalling(true);
    try {
      await http.post("/voice/calls", { phone_number_id: number.id, to: normalize(to), greeting: greeting || null });
      toast.success(t("calling", { to: normalize(to) }));
      void qc.invalidateQueries({ queryKey: ["voice", "calls"] });
      onClose();
    } catch (err) {
      toast.error(errorMessage(err, tc("errorGeneric")));
    } finally {
      setCalling(false);
    }
  };
  return (
    <Dialog open onOpenChange={(o) => (o ? null : onClose())}>
      <DialogContent
        title={t("callTitle")}
        description={t("callDescription", { number: number.number, agent: number.workforce_name })}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              {tc("cancel")}
            </Button>
            <Button variant="primary" loading={calling} disabled={!valid} onClick={() => void call()}>
              <PhoneOutgoing />
              {t("callNow")}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label={t("callTo")} hint={t("callToHint")} error={to && !valid ? t("invalidNumber") : undefined}>
            <Input value={to} inputMode="tel" placeholder="+34 600 000 000" onChange={(e) => setTo(e.target.value)} />
          </Field>
          <Field label={t("callGreeting")} hint={t("callGreetingHint")}>
            <Textarea value={greeting} rows={2} maxLength={500} onChange={(e) => setGreeting(e.target.value)} />
          </Field>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Channels → Phone: the project's phone numbers (Twilio / Telnyx), which agent answers each, outbound test
 * calls and recent phone calls. Without provider credentials it shows the setup state.
 */
export function PhoneSettings({ projectId }: { projectId: string }) {
  const t = useTranslations("voice.phone");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const status = useVoiceStatus();
  const numbers = usePhoneNumbers(projectId);
  const isAdmin = useRole("admin");
  const isBuilder = useRole("builder");
  const [assignOpen, setAssignOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<PhoneNumber | null>(null);
  const [calling, setCalling] = React.useState<PhoneNumber | null>(null);
  const [removing, setRemoving] = React.useState<PhoneNumber | null>(null);
  const [release, setRelease] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  if (status.isLoading || numbers.isLoading) return <SkeletonRows rows={5} />;
  if (status.isError || numbers.isError) {
    const err = status.error ?? numbers.error;
    return (
      <ErrorState
        title={tc("errorTitle")}
        description={errorMessage(err, tc("errorGeneric"))}
        onRetry={() => {
          void status.refetch();
          void numbers.refetch();
        }}
        retryLabel={tc("retry")}
      />
    );
  }
  const telephony = status.data?.telephony ?? { twilio: false, telnyx: false };
  const providers = (Object.keys(telephony) as PhoneProvider[]).filter((p) => telephony[p]);
  const missing = (status.data?.missing ?? []).filter((m) => m.feature === "phone");
  const rows = numbers.data ?? [];

  const remove = async () => {
    if (!removing) return;
    setBusy(true);
    try {
      await http.del(`/voice/numbers/${removing.id}${release ? "?release=true" : ""}`);
      toast.success(release ? t("released", { number: removing.number }) : t("unassigned", { number: removing.number }));
      void qc.invalidateQueries({ queryKey: voiceKeys.numbers(projectId) });
      setRemoving(null);
      setRelease(false);
    } catch (err) {
      toast.error(errorMessage(err, tc("errorGeneric")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      {providers.length === 0 ? (
        <Alert tone="info" title={t("setupTitle")}>
          <p>{t("setupBody")}</p>
          <ul className="mt-2 list-disc space-y-0.5 pl-5 font-mono text-xs">
            {missing.map((m) => (
              <li key={m.variable}>{m.variable}</li>
            ))}
          </ul>
          <p className="mt-2">{t("setupWebhooks")}</p>
        </Alert>
      ) : null}
      {providers.length > 0 && status.data && !status.data.audio.available ? (
        <Alert tone="warning" title={t("needsAudioTitle")}>
          {t("needsAudioBody")}
        </Alert>
      ) : null}

      <Card>
        <CardHeader
          title={t("numbersTitle")}
          description={t("numbersDescription")}
          actions={
            isAdmin && providers.length > 0 ? (
              <Button size="sm" variant="primary" onClick={() => setAssignOpen(true)}>
                <Plus />
                {t("addNumber")}
              </Button>
            ) : null
          }
        />
        <CardBody>
          {rows.length === 0 ? (
            <EmptyState
              icon={<Phone />}
              title={t("emptyTitle")}
              description={providers.length ? t("emptyDescription") : t("emptySetup")}
            />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{t("number")}</TH>
                  <TH>{t("agent")}</TH>
                  <TH>{t("environment")}</TH>
                  <TH>{tc("status")}</TH>
                  <TH>
                    <span className="sr-only">{tc("actions")}</span>
                  </TH>
                </tr>
              </THead>
              <TBody>
                {rows.map((n) => (
                  <TR key={n.id}>
                    <TD>
                      <p className="tabular font-medium">{n.number}</p>
                      <p className="text-xs text-fg-muted">
                        {t(`providers.${n.provider}`)}
                        {n.label ? ` · ${n.label}` : ""}
                      </p>
                    </TD>
                    <TD>{n.workforce_name}</TD>
                    <TD>
                      <Badge tone={n.environment === "production" ? "accent" : "outline"}>
                        {n.environment === "production" ? t("production") : t("development")}
                      </Badge>
                      {n.record_calls ? <Badge className="ml-1">{t("recorded")}</Badge> : null}
                    </TD>
                    <TD>
                      <Badge tone={n.status === "active" ? "success" : "danger"} title={n.error ?? undefined}>
                        {n.status === "active" ? t("active") : t("error")}
                      </Badge>
                    </TD>
                    <TD>
                      <div className="flex justify-end gap-1">
                        {isBuilder ? (
                          <>
                            <Button size="icon-sm" variant="ghost" aria-label={t("callTitle")} onClick={() => setCalling(n)}>
                              <PhoneOutgoing />
                            </Button>
                            <Button size="icon-sm" variant="ghost" aria-label={tc("edit")} onClick={() => setEditing(n)}>
                              <Pencil />
                            </Button>
                          </>
                        ) : null}
                        {isAdmin ? (
                          <Button size="icon-sm" variant="ghost" aria-label={tc("remove")} onClick={() => setRemoving(n)}>
                            <Trash2 />
                          </Button>
                        ) : null}
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">{t("recentCalls")}</h2>
        <VoiceCallsList projectId={projectId} channel="phone" emptyDescription={t("noCalls")} />
      </section>

      {assignOpen ? (
        <AssignNumberDialog projectId={projectId} providers={providers} open={assignOpen} onOpenChange={setAssignOpen} />
      ) : null}
      {editing ? <EditNumberDialog projectId={projectId} number={editing} onClose={() => setEditing(null)} /> : null}
      {calling ? <OutboundCallDialog number={calling} onClose={() => setCalling(null)} /> : null}
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(o) => (o ? null : setRemoving(null))}
        title={t("removeTitle", { number: removing?.number ?? "" })}
        description={t("removeDescription")}
        confirmLabel={release ? t("releaseConfirm") : t("unassignConfirm")}
        cancelLabel={tc("cancel")}
        destructive
        loading={busy}
        onConfirm={remove}
      >
        <div className="flex items-start gap-2">
          <Checkbox id="voice-release" checked={release} onCheckedChange={(v) => setRelease(v === true)} />
          <Label htmlFor="voice-release" className="font-normal">
            {t("releaseToo", { provider: removing ? t(`providers.${removing.provider}`) : "" })}
          </Label>
        </div>
      </ConfirmDialog>
    </div>
  );
}

"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CodeBlock,
  Dialog,
  DialogContent,
  Field,
  Input,
  PageHeader,
  Select,
  SkeletonRows,
  toast,
} from "@messer/ui";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import QRCode from "qrcode";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { useInvalidateMe, useMe } from "@/lib/hooks/use-me";

export default function ProfilePage() {
  const t = useTranslations("settings.profile");
  const ts = useTranslations("settings.sections");
  const tc = useTranslations("common");
  const router = useRouter();
  const { data: me, isLoading } = useMe();
  const invalidate = useInvalidateMe();
  const [name, setName] = React.useState("");
  const [locale, setLocale] = React.useState<"es" | "en">("es");
  const [setup, setSetup] = React.useState<{ secret: string; qr: string } | null>(null);
  const [recovery, setRecovery] = React.useState<string[] | null>(null);
  const [disableOpen, setDisableOpen] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (me) {
      setName(me.name ?? "");
      setLocale(me.locale);
    }
  }, [me]);

  const save = useMutation({
    mutationFn: () => http.patch("/me", { name, locale }),
    onSuccess: async () => {
      document.cookie = `NEXT_LOCALE=${locale}; Path=/; Max-Age=31536000; SameSite=Lax`;
      await invalidate();
      toast.success(tc("saved"));
      router.refresh();
    },
  });

  const startMfa = async () => {
    setError(null);
    const res = await http.post<{ secret: string; otpauth_uri: string }>("/auth/mfa/setup");
    setSetup({ secret: res.secret, qr: await QRCode.toDataURL(res.otpauth_uri, { margin: 1, width: 176 }) });
  };

  const confirmMfa = async (code: string) => {
    setError(null);
    try {
      const res = await http.post<{ recovery_codes: string[] }>("/auth/mfa/confirm", { code });
      setSetup(null);
      setRecovery(res.recovery_codes);
      await invalidate();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  };

  const disableMfa = async (code: string) => {
    setError(null);
    try {
      await http.post("/auth/mfa/disable", { code });
      setDisableOpen(false);
      await invalidate();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  };

  if (isLoading || !me) return <SkeletonRows rows={6} />;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={ts("profile")} description={t("description")} />
      {!me.email_verified ? (
        <Alert
          tone="warning"
          action={
            <Button
              size="sm"
              variant="secondary"
              onClick={async () => {
                await http.post("/auth/verify-email/resend");
                toast.success(t("verificationSent"));
              }}
            >
              {t("resendVerification")}
            </Button>
          }
        >
          {t("emailUnverified")}
        </Alert>
      ) : null}
      <Card>
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <Field label={t("name")} htmlFor="name">
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label={t("email")} htmlFor="email">
            <Input id="email" value={me.email} disabled />
          </Field>
          <Field label={t("language")}>
            <Select
              value={locale}
              onValueChange={(v) => setLocale(v as "es" | "en")}
              options={[
                { value: "es", label: "Español" },
                { value: "en", label: "English" },
              ]}
            />
          </Field>
        </CardBody>
        <CardFooter>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
            {tc("save")}
          </Button>
        </CardFooter>
      </Card>

      <Card>
        <CardHeader
          title={t("mfa")}
          actions={
            me.mfa_enabled ? (
              <>
                <Badge tone="success">{t("mfaEnabled")}</Badge>
                <Button variant="secondary" size="sm" onClick={() => setDisableOpen(true)}>
                  {t("mfaDisable")}
                </Button>
              </>
            ) : (
              <>
                <Badge>{t("mfaDisabled")}</Badge>
                <Button variant="secondary" size="sm" onClick={() => void startMfa()}>
                  {t("mfaEnable")}
                </Button>
              </>
            )
          }
        />
        {setup ? (
          <CardBody className="flex flex-col gap-4 sm:flex-row">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={setup.qr} alt="QR" width={176} height={176} className="rounded-md border border-border" />
            <form
              className="flex flex-1 flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                void confirmMfa(String(new FormData(e.currentTarget).get("code")));
              }}
            >
              <p className="text-sm text-fg-muted">{t("mfaScan")}</p>
              <Field label={t("mfaSecret")}>
                <code className="rounded-md bg-subtle px-2 py-1 font-mono text-xs">{setup.secret}</code>
              </Field>
              {error ? <Alert tone="danger">{error}</Alert> : null}
              <Field label={t("mfaCodePrompt")} htmlFor="mfa-code">
                <Input id="mfa-code" name="code" inputMode="numeric" autoComplete="one-time-code" required />
              </Field>
              <Button type="submit" variant="primary" className="self-start">
                {t("mfaEnable")}
              </Button>
            </form>
          </CardBody>
        ) : null}
        {recovery ? (
          <CardBody className="flex flex-col gap-2">
            <Alert tone="warning">{t("mfaRecovery")}</Alert>
            <CodeBlock code={recovery.join("\n")} />
          </CardBody>
        ) : null}
      </Card>

      <Dialog open={disableOpen} onOpenChange={setDisableOpen}>
        <DialogContent title={t("mfaDisable")}>
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              void disableMfa(String(new FormData(e.currentTarget).get("code")));
            }}
          >
            {error ? <Alert tone="danger">{error}</Alert> : null}
            <Field label={t("mfaCodePrompt")} htmlFor="mfa-disable-code">
              <Input id="mfa-disable-code" name="code" inputMode="numeric" required autoFocus />
            </Field>
            <Button type="submit" variant="primary">
              {t("mfaDisable")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

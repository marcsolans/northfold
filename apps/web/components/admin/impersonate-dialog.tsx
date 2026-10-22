"use client";

import { Alert, Button, Dialog, DialogContent, Field, Select, Textarea } from "@messer/ui";
import { useMutation } from "@tanstack/react-query";
import { LogIn } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";

export interface ImpersonationTarget {
  userId: string;
  email: string;
  orgs: { id: string; name: string }[];
  orgId?: string;
}

/** "Log in as" with a mandatory reason (audited). The session carries the impersonation banner. */
export function ImpersonateDialog({ target, onClose }: { target: ImpersonationTarget | null; onClose: () => void }) {
  const t = useTranslations("admin");
  const tc = useTranslations("common");
  const [reason, setReason] = React.useState("");
  const [orgId, setOrgId] = React.useState<string>("");
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    setReason("");
    setError(null);
    setOrgId(target?.orgId ?? target?.orgs[0]?.id ?? "");
  }, [target]);
  const start = useMutation({
    mutationFn: () =>
      http.post<{ redirect: string }>("/admin/impersonation/start", {
        user_id: target?.userId ?? "",
        org_id: orgId || null,
        reason: reason.trim(),
      }),
    onSuccess: (res) => {
      // Full reload: every cached query belongs to the superadmin session.
      window.location.assign(res.redirect);
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });
  const valid = reason.trim().length >= 3;
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title={t("impersonate.title", { email: target?.email ?? "" })}
        description={t("impersonate.description")}
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) start.mutate();
          }}
        >
          {error ? <Alert tone="danger">{error}</Alert> : null}
          {target && target.orgs.length > 1 ? (
            <Field label={t("impersonate.org")}>
              <Select value={orgId} onValueChange={setOrgId} options={target.orgs.map((o) => ({ value: o.id, label: o.name }))} />
            </Field>
          ) : null}
          <Field label={t("impersonate.reason")} htmlFor="imp-reason" hint={t("impersonate.reasonHint")}>
            <Textarea id="imp-reason" required autoFocus value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <div className="mt-2 flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose}>
              {tc("cancel")}
            </Button>
            <Button type="submit" variant="primary" loading={start.isPending} disabled={!valid}>
              <LogIn />
              {t("impersonate.confirm")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

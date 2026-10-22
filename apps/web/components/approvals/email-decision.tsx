"use client";

import { Alert, Badge, Button, Field, SkeletonRows, Textarea } from "@messer/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock, ShieldX, XCircle } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { ApiError, http } from "@/lib/api";
import { formatDate, localeTag } from "@/lib/format";
import type { ApprovalLink, ApprovalLinkResult } from "@/lib/studio/types";

import { ApprovalStatusBadge } from "./approval-status-badge";
import { PayloadView } from "./payload-view";

type Problem = "invalid" | "forbidden" | "notFound" | "decided" | "expired" | "generic";

function problemOf(err: unknown): Problem {
  if (!(err instanceof ApiError)) return "generic";
  if (err.status === 403) return "forbidden";
  if (err.status === 404) return "notFound";
  if (err.code === "expired") return "expired";
  if (err.code === "already_decided" || err.status === 409) return "decided";
  if (err.status === 400 || err.status === 422) return "invalid";
  return "generic";
}

function StateCard({
  icon,
  tone,
  title,
  description,
  children,
}: {
  icon: React.ReactNode;
  tone: "success" | "danger" | "warning" | "neutral";
  title: string;
  description?: string;
  children?: React.ReactNode;
}) {
  const color = { success: "text-success", danger: "text-danger", warning: "text-warning", neutral: "text-fg-subtle" }[tone];
  return (
    <div className="rounded-md border border-border bg-surface p-6 text-center" role={tone === "danger" ? "alert" : "status"}>
      <div className={`mx-auto mb-3 flex justify-center [&_svg]:size-8 ${color}`}>{icon}</div>
      <h1 className="text-lg font-semibold">{title}</h1>
      {description ? <p className="mx-auto mt-1.5 max-w-sm text-sm text-fg-muted">{description}</p> : null}
      {children ? <div className="mt-4">{children}</div> : null}
    </div>
  );
}

/** Email decision links: opening the link only shows what will be decided; the decision needs a confirmation. */
export function EmailDecision() {
  const t = useTranslations("approvals.email");
  const tc = useTranslations("common");
  const locale = localeTag(useLocale());
  const token = useSearchParams().get("token") ?? "";
  const [comment, setComment] = React.useState("");
  const [commentError, setCommentError] = React.useState<string | null>(null);

  const link = useQuery({
    queryKey: ["approval-link", token],
    queryFn: () => http.get<ApprovalLink>("/api/v1/approval-links", { token }),
    enabled: token.length > 0,
    retry: false,
  });
  const decide = useMutation({
    mutationFn: () =>
      http.post<ApprovalLinkResult>("/api/v1/approval-links", { token, ...(comment.trim() ? { comment: comment.trim() } : {}) }),
  });

  const signIn = (
    <Button asChild variant="secondary">
      <Link href="/app/approvals">{t("openInbox")}</Link>
    </Button>
  );

  if (!token) return <StateCard icon={<ShieldX />} tone="danger" title={t("problems.invalid.title")} description={t("problems.invalid.description")} />;
  if (link.isLoading) {
    return (
      <div className="rounded-md border border-border bg-surface p-6">
        <SkeletonRows rows={5} />
      </div>
    );
  }
  if (link.error || !link.data) {
    const problem = problemOf(link.error);
    return (
      <StateCard
        icon={problem === "forbidden" ? <ShieldX /> : <XCircle />}
        tone="danger"
        title={t(`problems.${problem}.title`)}
        description={t(`problems.${problem}.description`)}
      >
        {problem === "generic" ? (
          <Button variant="secondary" onClick={() => void link.refetch()}>
            {tc("retry")}
          </Button>
        ) : (
          signIn
        )}
      </StateCard>
    );
  }

  const data = link.data;
  const approve = data.decision === "approve";

  if (decide.isSuccess) {
    const result = decide.data;
    return (
      <StateCard
        icon={result.status === "approved" ? <CheckCircle2 /> : <XCircle />}
        tone={result.status === "approved" ? "success" : "danger"}
        title={result.status === "approved" ? t("done.approved") : t("done.denied")}
        description={result.resumed ? t("done.resumed") : t("done.waiting")}
      >
        {signIn}
      </StateCard>
    );
  }
  if (decide.error) {
    const problem = problemOf(decide.error);
    return (
      <StateCard icon={<XCircle />} tone="danger" title={t(`problems.${problem}.title`)} description={t(`problems.${problem}.description`)}>
        {signIn}
      </StateCard>
    );
  }

  if (data.status !== "pending") {
    return (
      <StateCard icon={<Clock />} tone="neutral" title={t("alreadyDecided")} description={data.title}>
        <div className="flex flex-col items-center gap-3">
          <ApprovalStatusBadge status={data.status} />
          {signIn}
        </div>
      </StateCard>
    );
  }
  if (data.expires_at && new Date(data.expires_at).getTime() <= Date.now()) {
    return <StateCard icon={<Clock />} tone="warning" title={t("problems.expired.title")} description={t("problems.expired.description")} />;
  }

  const confirm = () => {
    if (!approve && !comment.trim()) {
      setCommentError(t("commentRequired"));
      return;
    }
    decide.mutate();
  };

  return (
    <div className="rounded-md border border-border bg-surface">
      <div className="border-b border-border p-5">
        <Badge tone={approve ? "success" : "danger"}>{approve ? t("willApprove") : t("willDeny")}</Badge>
        <h1 className="mt-2 text-lg font-semibold">{data.title || t("fallbackTitle", { tool: data.tool_name })}</h1>
        <dl className="mt-3 grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-1 text-sm">
          <dt className="text-fg-subtle">{t("project")}</dt>
          <dd>{data.project_name ?? "—"}</dd>
          <dt className="text-fg-subtle">{t("agent")}</dt>
          <dd className="font-mono text-xs leading-5">{data.workforce_name}</dd>
          <dt className="text-fg-subtle">{t("tool")}</dt>
          <dd className="font-mono text-xs leading-5">{data.tool_name}</dd>
          {data.expires_at ? (
            <>
              <dt className="text-fg-subtle">{t("expires")}</dt>
              <dd>{formatDate(data.expires_at, locale, true)}</dd>
            </>
          ) : null}
        </dl>
      </div>
      <div className="flex flex-col gap-4 p-5">
        <section>
          <h2 className="mb-2 text-sm font-semibold">{t("payload")}</h2>
          <PayloadView payload={data.payload} />
        </section>
        <Field
          label={approve ? t("comment") : t("denyReason")}
          htmlFor="email-comment"
          hint={approve ? tc("optional") : t("denyReasonHint")}
          error={commentError}
        >
          <Textarea
            id="email-comment"
            rows={3}
            value={comment}
            maxLength={4000}
            aria-invalid={Boolean(commentError) || undefined}
            onChange={(e) => {
              setComment(e.target.value);
              setCommentError(null);
            }}
          />
        </Field>
        <Alert tone="info">{t("notice")}</Alert>
        <Button size="lg" variant={approve ? "primary" : "danger"} loading={decide.isPending} onClick={confirm} className="w-full">
          {approve ? t("confirmApprove") : t("confirmDeny")}
        </Button>
        <p className="text-center text-xs text-fg-subtle">
          {t("changeMind")}{" "}
          <Link href="/app/approvals" className="underline underline-offset-2">
            {t("openInbox")}
          </Link>
        </p>
      </div>
    </div>
  );
}

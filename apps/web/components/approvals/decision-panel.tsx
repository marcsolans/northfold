"use client";

import { Alert, Button, Field, Textarea } from "@messer/ui";
import { Check, PencilLine, X } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import type { Decision, DecisionBody, JsonSchema } from "@/lib/studio/types";
import type { Role } from "@/lib/types";

import { PayloadEditor, type PayloadEditorState, changedFields } from "./payload-editor";

/** Approve / deny (comment required) / approve with changes. Shared by the playground card and the inbox. */
export function DecisionPanel({
  idPrefix,
  payload,
  schema,
  canDecide,
  assignedRole,
  busy,
  error,
  onDecide,
}: {
  idPrefix: string;
  payload: Record<string, unknown>;
  schema: JsonSchema | null;
  canDecide: boolean;
  assignedRole: Role | null;
  busy: Decision | null;
  error?: string | null;
  onDecide: (body: DecisionBody) => void;
}) {
  const t = useTranslations("approvals.decide");
  const tc = useTranslations("common");
  const [mode, setMode] = React.useState<"deny" | "changes" | null>(null);
  const [comment, setComment] = React.useState("");
  const [commentError, setCommentError] = React.useState<string | null>(null);
  const [edited, setEdited] = React.useState<PayloadEditorState>({ value: payload, error: null });
  const [changesError, setChangesError] = React.useState<string | null>(null);
  const onEditorChange = React.useCallback((state: PayloadEditorState) => {
    setEdited(state);
    setChangesError(null);
  }, []);

  if (!canDecide) {
    return (
      <Alert tone="info">
        {assignedRole ? t("needsRole", { role: tc(`roles.${assignedRole}`) }) : t("cannotDecide")}
      </Alert>
    );
  }

  const reset = () => {
    setMode(null);
    setComment("");
    setCommentError(null);
    setChangesError(null);
  };

  const confirmDeny = () => {
    if (!comment.trim()) {
      setCommentError(t("commentRequired"));
      return;
    }
    onDecide({ decision: "deny", comment: comment.trim() });
  };

  const confirmChanges = () => {
    if (!edited.value) {
      setChangesError(edited.error ?? t("invalidChanges"));
      return;
    }
    const changes = changedFields(payload, edited.value);
    if (Object.keys(changes).length === 0) {
      setChangesError(t("noChanges"));
      return;
    }
    onDecide({ decision: "approve_with_changes", payload: changes, ...(comment.trim() ? { comment: comment.trim() } : {}) });
  };

  const disabled = busy !== null;
  return (
    <div className="flex flex-col gap-3">
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {mode === null ? (
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" loading={busy === "approve"} disabled={disabled} onClick={() => onDecide({ decision: "approve" })}>
            <Check />
            {t("approve")}
          </Button>
          <Button variant="secondary" disabled={disabled} onClick={() => setMode("changes")}>
            <PencilLine />
            {t("approveWithChanges")}
          </Button>
          <Button variant="danger" disabled={disabled} onClick={() => setMode("deny")}>
            <X />
            {t("deny")}
          </Button>
        </div>
      ) : mode === "deny" ? (
        <div className="flex flex-col gap-3">
          <Field label={t("denyReason")} htmlFor={`${idPrefix}-deny`} error={commentError} hint={t("denyReasonHint")}>
            <Textarea
              id={`${idPrefix}-deny`}
              autoFocus
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
          <div className="flex gap-2">
            <Button variant="danger" loading={busy === "deny"} disabled={disabled} onClick={confirmDeny}>
              {t("confirmDeny")}
            </Button>
            <Button variant="ghost" disabled={disabled} onClick={reset}>
              {tc("cancel")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <PayloadEditor idPrefix={`${idPrefix}-edit`} payload={payload} schema={schema} onChange={onEditorChange} />
          <Field label={t("comment")} htmlFor={`${idPrefix}-comment`} hint={tc("optional")}>
            <Textarea id={`${idPrefix}-comment`} rows={2} value={comment} maxLength={4000} onChange={(e) => setComment(e.target.value)} />
          </Field>
          {changesError ? (
            <p className="text-xs text-danger" role="alert">
              {changesError}
            </p>
          ) : null}
          <div className="flex gap-2">
            <Button variant="primary" loading={busy === "approve_with_changes"} disabled={disabled} onClick={confirmChanges}>
              {t("confirmChanges")}
            </Button>
            <Button variant="ghost" disabled={disabled} onClick={reset}>
              {tc("cancel")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

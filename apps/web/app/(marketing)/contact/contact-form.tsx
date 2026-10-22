"use client";

import { Alert, Button, Field, Input, Textarea, inputClass } from "@messer/ui";
import { CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { z } from "zod";

import { ApiError, http } from "@/lib/api";
import { CONTACT_TOPICS, type ContactTopic } from "@/lib/marketing/contact";

type FieldName = "name" | "email" | "company" | "message";
type Errors = Partial<Record<FieldName, string>>;

const schema = z.object({
  name: z.string().trim().min(1, "required").max(200, "tooLong"),
  email: z.string().trim().min(1, "required").pipe(z.email("email")),
  company: z.string().trim().max(200, "tooLong"),
  message: z.string().trim().min(10, "messageShort").max(5000, "tooLong"),
});

export function ContactForm({ initialTopic }: { initialTopic: ContactTopic }) {
  const t = useTranslations("contact");
  const locale = useLocale();
  const [errors, setErrors] = React.useState<Errors>({});
  const [formError, setFormError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [sent, setSent] = React.useState<{ name: string; email: string } | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const values = {
      name: String(form.get("name") ?? ""),
      email: String(form.get("email") ?? ""),
      company: String(form.get("company") ?? ""),
      message: String(form.get("message") ?? ""),
    };
    const parsed = schema.safeParse(values);
    if (!parsed.success) {
      const next: Errors = {};
      for (const issue of parsed.error.issues) {
        const field = issue.path[0] as FieldName | undefined;
        if (field && !next[field]) next[field] = t(`errors.${issue.message as "required"}`);
      }
      setErrors(next);
      setFormError(t("errors.validation"));
      return;
    }
    setErrors({});
    setFormError(null);
    setSubmitting(true);
    try {
      await http.post("/contact", {
        ...parsed.data,
        company: parsed.data.company || null,
        topic: String(form.get("topic") ?? "sales"),
        locale: locale === "en" ? "en" : "es",
        website: String(form.get("website") ?? ""),
      });
      setSent({ name: parsed.data.name, email: parsed.data.email });
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setFormError(t("errors.rateLimited"));
      } else if (err instanceof ApiError && err.status === 422) {
        const details = (err.details.errors ?? []) as { loc?: string[] }[];
        const next: Errors = {};
        for (const d of details) {
          const field = d.loc?.[d.loc.length - 1] as FieldName | undefined;
          if (field && ["name", "email", "company", "message"].includes(field)) next[field] = t("errors.validation");
        }
        setErrors(next);
        setFormError(t("errors.validation"));
      } else {
        setFormError(t("errors.generic"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (sent) {
    return (
      <div role="status" className="rounded-md border border-success/25 bg-success-soft p-6">
        <CheckCircle2 className="size-5 text-success" aria-hidden />
        <p className="mt-3 text-md font-semibold text-fg">{t("success.title")}</p>
        <p className="mt-1 text-sm text-fg-muted">{t("success.body", sent)}</p>
        <Button variant="secondary" className="mt-4" onClick={() => setSent(null)}>
          {t("success.another")}
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4 rounded-md border border-border bg-surface p-5 sm:p-6">
      {formError ? <Alert tone="danger">{formError}</Alert> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("form.name")} htmlFor="contact-name" error={errors.name}>
          <Input id="contact-name" name="name" autoComplete="name" required maxLength={200} aria-invalid={Boolean(errors.name)} />
        </Field>
        <Field label={t("form.email")} htmlFor="contact-email" error={errors.email}>
          <Input
            id="contact-email"
            name="email"
            type="email"
            autoComplete="email"
            required
            maxLength={320}
            aria-invalid={Boolean(errors.email)}
          />
        </Field>
        <Field
          label={
            <>
              {t("form.company")} <span className="font-normal text-fg-subtle">({t("form.optional")})</span>
            </>
          }
          htmlFor="contact-company"
          error={errors.company}
        >
          <Input id="contact-company" name="company" autoComplete="organization" maxLength={200} aria-invalid={Boolean(errors.company)} />
        </Field>
        <Field label={t("form.topic")} htmlFor="contact-topic">
          <select id="contact-topic" name="topic" defaultValue={initialTopic} className={`${inputClass} appearance-auto pr-2`}>
            {CONTACT_TOPICS.map((topic) => (
              <option key={topic} value={topic}>
                {t(`form.topics.${topic}`)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label={t("form.message")} htmlFor="contact-message" hint={t("form.messageHint")} error={errors.message}>
        <Textarea
          id="contact-message"
          name="message"
          rows={6}
          required
          maxLength={5000}
          placeholder={t("form.messagePlaceholder")}
          aria-invalid={Boolean(errors.message)}
        />
      </Field>
      {/* Honeypot: invisible to people and assistive technology, filled in by naive bots. */}
      <div aria-hidden className="absolute -left-[10000px] top-auto size-px overflow-hidden">
        <label htmlFor="contact-website">{t("form.honeypot")}</label>
        <input id="contact-website" name="website" type="text" tabIndex={-1} autoComplete="off" defaultValue="" />
      </div>
      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-fg-subtle">
          {t.rich("form.privacy", {
            link: (chunks) => (
              <Link href="/legal/privacy" className="underline underline-offset-2">
                {chunks}
              </Link>
            ),
          })}
        </p>
        <Button type="submit" variant="primary" loading={submitting} className="shrink-0">
          {t("form.submit")}
        </Button>
      </div>
    </form>
  );
}

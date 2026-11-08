"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import { ArrowBox } from "./primitives";

export type EmailFormMessages = {
  required: string;
  invalid: string;
  sending: string;
  success: string;
  error: string;
  fallback: string;
};

type Props = {
  /** Where the lead came from, sent to /api/lead and used as the form id prefix. */
  source: "hero" | "contact";
  locale: string;
  placeholder: string;
  cta: string;
  /** Subject for the mailto fallback (the localized CTA label). */
  mailSubject: string;
  email: string;
  messages: EmailFormMessages;
  tone?: "hero" | "contact";
  className?: string;
};

type Status = { kind: "idle" | "sending" | "success" | "error" | "invalid" | "fallback"; text?: string; value?: string };

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/**
 * Inline email form: input flush with the black button, stacked under 640px.
 * Validates client-side, then POSTs JSON to /api/lead. If the server has no mail
 * provider configured it answers { fallback: "mailto" } and we open the visitor's
 * mail app instead. Without JS the form still posts (form-encoded) to the same route.
 */
export function EmailForm({ source, locale, placeholder, cta, mailSubject, email, messages, tone = "hero", className = "" }: Props) {
  const uid = useId();
  const inputId = `${source}-email-${uid}`;
  const statusId = `${source}-status-${uid}`;
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const mailtoFor = (value: string) =>
    `mailto:${email}?subject=${encodeURIComponent(mailSubject)}&body=${encodeURIComponent(value)}`;

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const value = (inputRef.current?.value ?? "").trim();
    if (!value) return setStatus({ kind: "invalid", text: messages.required });
    if (!EMAIL.test(value)) return setStatus({ kind: "invalid", text: messages.invalid });

    setStatus({ kind: "sending", text: messages.sending });
    try {
      const res = await fetch("/api/lead", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: value,
          source,
          locale,
          website: (form.elements.namedItem("website") as HTMLInputElement | null)?.value ?? "",
        }),
      });
      const data = (await res.json().catch(() => ({}))) as { ok?: boolean; fallback?: string };
      if (res.ok && data.ok) {
        form.reset();
        return setStatus({ kind: "success", text: messages.success });
      }
      if (data.fallback === "mailto") {
        setStatus({ kind: "fallback", text: messages.fallback });
        window.location.href = mailtoFor(value);
        return;
      }
      if (res.status === 400) return setStatus({ kind: "invalid", text: messages.invalid });
      setStatus({ kind: "error", text: messages.error, value });
    } catch {
      setStatus({ kind: "error", text: messages.error, value });
    }
  }

  const invalid = status.kind === "invalid";
  const inputTone =
    tone === "hero"
      ? "h-[46px] border-stone bg-white/40"
      : "h-11 border-[rgba(46,46,46,0.3)] bg-transparent";

  return (
    <div className={className}>
      <form
        action="/api/lead"
        method="post"
        noValidate
        onSubmit={onSubmit}
        className="inline-form w-full max-w-[480px]"
        aria-describedby={statusId}
      >
        <input type="hidden" name="source" value={source} />
        <input type="hidden" name="locale" value={locale} />
        {/* Honeypot: hidden from people and assistive tech; bots tend to fill it. */}
        <div aria-hidden="true" className="absolute -start-[9999px] size-px overflow-hidden">
          <label htmlFor={`${inputId}-website`}>Website</label>
          <input id={`${inputId}-website`} name="website" type="text" tabIndex={-1} autoComplete="off" />
        </div>
        <label htmlFor={inputId} className="sr-only">
          {placeholder}
        </label>
        <input
          ref={inputRef}
          id={inputId}
          name="email"
          type="email"
          inputMode="email"
          autoComplete="email"
          required
          placeholder={placeholder}
          aria-invalid={invalid || undefined}
          aria-describedby={statusId}
          onInput={() => invalid && setStatus({ kind: "idle" })}
          className={`w-full min-w-0 border px-4 sm:w-auto sm:flex-1 text-sm text-obsidian outline-none transition-colors placeholder:text-concrete focus-visible:border-obsidian focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rust ${inputTone} ${
            invalid ? "!border-alert" : ""
          }`}
        />
        <button type="submit" className="btn" disabled={status.kind === "sending"}>
          {cta}
          <ArrowBox />
        </button>
      </form>
      <p
        id={statusId}
        role="status"
        aria-live="polite"
        className={`m-0 text-xs ${status.text ? "mt-2" : ""} ${invalid || status.kind === "error" ? "text-alert" : "text-carbon"}`}
      >
        {status.text}
        {status.kind === "error" && (
          <>
            {" "}
            <a href={mailtoFor(status.value ?? "")} className="underline">
              {email}
            </a>
          </>
        )}
      </p>
    </div>
  );
}

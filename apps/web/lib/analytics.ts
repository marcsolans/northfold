"use client";

/** Product analytics (PostHog EU). Loaded only after explicit cookie consent. */

const CONSENT_COOKIE = "messer_consent";

export type Consent = "accepted" | "rejected";

export function readConsent(): Consent | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|; )messer_consent=(accepted|rejected)/);
  return (match?.[1] as Consent | undefined) ?? null;
}

export function writeConsent(value: Consent): void {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${CONSENT_COOKIE}=${value}; Max-Age=${60 * 60 * 24 * 180}; Path=/; SameSite=Lax${secure}`;
}

let started = false;

export async function startAnalytics(): Promise<void> {
  const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
  if (started || !key || readConsent() !== "accepted") return;
  started = true;
  const { default: posthog } = await import("posthog-js");
  posthog.init(key, {
    api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://eu.i.posthog.com",
    persistence: "localStorage+cookie",
    capture_pageview: true,
    autocapture: false,
    disable_session_recording: true,
  });
}

export async function track(event: string, properties: Record<string, unknown> = {}): Promise<void> {
  if (!started) return;
  const { default: posthog } = await import("posthog-js");
  posthog.capture(event, properties);
}

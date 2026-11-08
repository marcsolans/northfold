import { site } from "@/lib/site";

export const LEAD_SOURCES = ["hero", "contact"] as const;
export type LeadSource = (typeof LEAD_SOURCES)[number];

const EMAIL = /^[^\s@<>"]+@[^\s@<>"]+\.[^\s@<>"]{2,}$/;
export const isEmail = (v: string) => v.length <= 254 && EMAIL.test(v);

export type Lead = { email: string; source: LeadSource; locale: string; userAgent?: string };

export type SendResult = { ok: true } | { ok: false; reason: "not_configured" | "provider_error" };

/**
 * Sends the lead to the team inbox through Resend's HTTP API.
 * Env: RESEND_API_KEY (required to send), RESEND_FROM (verified sender),
 * LEAD_TO (inbox; defaults to the public contact address).
 */
export async function sendLead(lead: Lead): Promise<SendResult> {
  const key = process.env.RESEND_API_KEY;
  if (!key) return { ok: false, reason: "not_configured" };

  const to = process.env.LEAD_TO || site.email;
  const from = process.env.RESEND_FROM || "Kofen website <onboarding@resend.dev>";
  const when = new Date().toISOString();
  const text = [
    `New demo request from the website.`,
    ``,
    `Email:   ${lead.email}`,
    `Form:    ${lead.source}`,
    `Locale:  ${lead.locale}`,
    `Time:    ${when}`,
    lead.userAgent ? `Agent:   ${lead.userAgent.slice(0, 200)}` : "",
  ]
    .filter(Boolean)
    .join("\n");

  try {
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from,
        to: [to],
        reply_to: lead.email,
        subject: `Demo request · ${lead.email}`,
        text,
      }),
      signal: AbortSignal.timeout(8000),
      cache: "no-store",
    });
    if (!res.ok) {
      console.error("[lead] Resend responded", res.status, await res.text().catch(() => ""));
      return { ok: false, reason: "provider_error" };
    }
    return { ok: true };
  } catch (err) {
    console.error("[lead] Resend request failed", err);
    return { ok: false, reason: "provider_error" };
  }
}

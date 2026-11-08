import { NextResponse, type NextRequest } from "next/server";
import { hasLocale } from "next-intl";
import { routing } from "@/i18n/routing";
import { LEAD_SOURCES, isEmail, sendLead, type LeadSource } from "@/lib/server/lead";
import { rateLimit } from "@/lib/server/rateLimit";
import { site } from "@/lib/site";

/**
 * POST /api/lead — demo requests from the hero and closing forms.
 *
 * Accepts JSON (the enhanced form) or form-encoded bodies (no-JS form post).
 * - honeypot `website` filled → pretend success, send nothing
 * - invalid email → 400
 * - more than 5 requests per IP in 10 minutes → 429
 * - RESEND_API_KEY missing or provider failure → 503 { fallback: "mailto" }
 */
type Body = { email?: unknown; source?: unknown; locale?: unknown; website?: unknown };

const json = (status: number, body: Record<string, unknown>, headers?: HeadersInit) =>
  NextResponse.json(body, { status, headers: { "Cache-Control": "no-store", ...headers } });

function clientIp(req: NextRequest) {
  return req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || req.headers.get("x-real-ip") || "unknown";
}

/** Plain HTML answer for no-JS form posts (escaped; no user input is reflected). */
function htmlAnswer(status: number, locale: string, title: string, linkText: string, href: string) {
  const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  const page = `<!doctype html><html lang="${esc(locale)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>Kofen</title></head><body style="font-family:system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 20px;color:#070707"><p style="font-size:20px;line-height:1.4">${esc(title)}</p><p><a href="${esc(href)}" style="color:#070707">${esc(linkText)}</a></p></body></html>`;
  return new NextResponse(page, { status, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}

async function loadFormMessages(locale: string) {
  const messages = (await import(`../../../messages/${locale}.json`)).default;
  return { form: messages.ui.form as Record<string, string>, back: messages.ui.notFound.back as string };
}

export async function POST(req: NextRequest) {
  // Same-origin only: browsers always send Origin on cross-site POSTs.
  const origin = req.headers.get("origin");
  if (origin && new URL(origin).host !== req.headers.get("host")) {
    return json(403, { ok: false, error: "forbidden" });
  }

  const type = req.headers.get("content-type") ?? "";
  const isForm = type.includes("application/x-www-form-urlencoded") || type.includes("multipart/form-data");
  let body: Body = {};
  try {
    body = isForm ? (Object.fromEntries(await req.formData()) as Body) : ((await req.json()) as Body);
  } catch {
    return json(400, { ok: false, error: "bad_request" });
  }

  const email = typeof body.email === "string" ? body.email.trim() : "";
  const source: LeadSource = LEAD_SOURCES.includes(body.source as LeadSource) ? (body.source as LeadSource) : "contact";
  const locale = typeof body.locale === "string" && hasLocale(routing.locales, body.locale) ? body.locale : routing.defaultLocale;
  const honeypot = typeof body.website === "string" && body.website.trim() !== "";

  const answer = async (status: number, key: "success" | "invalid" | "error" | "fallback", extra: Record<string, unknown> = {}) => {
    if (!isForm) return json(status, { ok: status < 300, ...extra });
    const { form, back } = await loadFormMessages(locale);
    if (key === "fallback" || key === "error") {
      return htmlAnswer(status, locale, form.error, site.email, `mailto:${site.email}`);
    }
    return htmlAnswer(status, locale, form[key], back, `/${locale}#contact`);
  };

  if (honeypot) return answer(200, "success");
  if (!isEmail(email)) return answer(400, "invalid", { error: "invalid_email" });

  const limited = rateLimit(clientIp(req));
  if (!limited.ok) {
    const res = await answer(429, "error", { error: "rate_limited" });
    res.headers.set("Retry-After", String(limited.retryAfter));
    return res;
  }

  const sent = await sendLead({ email, source, locale, userAgent: req.headers.get("user-agent") ?? undefined });
  if (!sent.ok) return answer(503, "fallback", { error: sent.reason, fallback: "mailto" });
  return answer(200, "success");
}

export function GET() {
  return json(405, { ok: false, error: "method_not_allowed" }, { Allow: "POST" });
}

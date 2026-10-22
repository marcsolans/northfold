import { type NextRequest, NextResponse } from "next/server";

const PROTECTED = ["/app", "/admin", "/onboarding"];

/** Custom domains of deployed environments (DECISIONS D-034): host → public pages of one project. */
type DomainTarget = { org: string; project: string; home: string | null } | null;
const domainCache = new Map<string, { target: DomainTarget; expires: number }>();
const DOMAIN_TTL_MS = 60_000;

function primaryHosts(): Set<string> {
  const hosts = new Set(["localhost", "127.0.0.1"]);
  for (const value of [process.env.MESSER_WEB_URL, process.env.NEXT_PUBLIC_MESSER_WEB_URL]) {
    if (!value) continue;
    try {
      hosts.add(new URL(value).hostname);
    } catch {
      // ignore malformed configuration
    }
  }
  return hosts;
}

async function resolveDomain(host: string): Promise<DomainTarget> {
  const cached = domainCache.get(host);
  if (cached && cached.expires > Date.now()) return cached.target;
  let target: DomainTarget = null;
  try {
    const api = process.env.MESSER_API_URL ?? "http://localhost:8000";
    const res = await fetch(`${api}/api/public/v1/domains/resolve?host=${encodeURIComponent(host)}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      const data = (await res.json()) as { org?: string; project?: string; home?: string | null };
      if (data.org && data.project) target = { org: data.org, project: data.project, home: data.home ?? null };
    }
  } catch {
    target = null;
  }
  domainCache.set(host, { target, expires: Date.now() + (target ? DOMAIN_TTL_MS : DOMAIN_TTL_MS / 2) });
  return target;
}

function customDomainPath(pathname: string, target: NonNullable<DomainTarget>): string {
  const base = `/${target.org}/${target.project}`;
  if (pathname.startsWith("/embed/")) return `/embed${base}${pathname.slice("/embed".length)}`;
  if (pathname === "/" || pathname === "") return `${base}${target.home ?? ""}`;
  return `${base}${pathname}`;
}

/**
 * Edge gate + strict CSP.
 * - Redirects unauthenticated visitors of the app to /login (the API is the real authority).
 * - Sets a per-request nonce-based Content-Security-Policy.
 */
export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const host = (request.headers.get("host") ?? "").split(":")[0]?.toLowerCase() ?? "";
  if (host && !primaryHosts().has(host)) {
    const target = await resolveDomain(host);
    if (target) {
      const url = request.nextUrl.clone();
      url.pathname = customDomainPath(pathname, target);
      return withSecurityHeaders(request, url.pathname, (headers) =>
        NextResponse.rewrite(url, { request: { headers } }),
      );
    }
  }
  const hasSession = request.cookies.has("messer_at") || request.cookies.has("messer_rt");
  if (PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`)) && !hasSession) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }

  return withSecurityHeaders(request, pathname, (headers) => NextResponse.next({ request: { headers } }));
}

/** ws(s):// origin of the voice service (browser calls), for the CSP connect-src. */
function voiceOrigin(): string {
  const raw = process.env.MESSER_VOICE_PUBLIC_URL || process.env.MESSER_VOICE_URL;
  if (!raw) return "";
  try {
    const url = new URL(raw);
    return ` ${url.protocol === "https:" ? "wss:" : "ws:"}//${url.host}`;
  } catch {
    return "";
  }
}

function withSecurityHeaders(
  request: NextRequest,
  pathname: string,
  respond: (headers: Headers) => NextResponse,
): NextResponse {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isDev = process.env.NODE_ENV !== "production";
  const posthogHost = process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://eu.i.posthog.com";
  const sentry = "https://*.ingest.de.sentry.io";
  const embeddable = pathname.startsWith("/embed/");
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    `connect-src 'self' ${posthogHost} ${sentry}${voiceOrigin()}${isDev ? " ws: http://localhost:*" : ""}`,
    "worker-src 'self' blob:",
    "media-src 'self' blob:",
    embeddable ? "frame-ancestors *" : "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self' https://checkout.stripe.com https://billing.stripe.com",
    "object-src 'none'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const lang = request.nextUrl.searchParams.get("lang");
  if (lang === "es" || lang === "en") requestHeaders.set("x-messer-locale", lang);
  const response = respond(requestHeaders);
  if (lang === "es" || lang === "en") {
    response.cookies.set("NEXT_LOCALE", lang, { path: "/", maxAge: 60 * 60 * 24 * 365, sameSite: "lax" });
  }
  response.headers.set("Content-Security-Policy", csp);
  if (!embeddable) response.headers.set("X-Frame-Options", "DENY");
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico|monaco|robots.txt|sitemap.xml|widget).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};

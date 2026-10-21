import { type NextRequest, NextResponse } from "next/server";

const PROTECTED = ["/app", "/admin", "/onboarding"];

/**
 * Edge gate + strict CSP.
 * - Redirects unauthenticated visitors of the app to /login (the API is the real authority).
 * - Sets a per-request nonce-based Content-Security-Policy.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const hasSession = request.cookies.has("messer_at") || request.cookies.has("messer_rt");
  if (PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`)) && !hasSession) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + search)}`;
    return NextResponse.redirect(url);
  }

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
    `connect-src 'self' ${posthogHost} ${sentry}${isDev ? " ws: http://localhost:*" : ""}`,
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
  const response = NextResponse.next({ request: { headers: requestHeaders } });
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

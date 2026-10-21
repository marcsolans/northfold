import { getSessionCookie } from "better-auth/cookies";
import { type NextRequest, NextResponse } from "next/server";

/**
 * Optimistic redirects only: if there is no session cookie at all, send the visitor to sign-in
 * before rendering a protected page. This never grants access — every page, Server Action and
 * route handler re-checks the session (and role) on the server.
 */
export function proxy(request: NextRequest) {
  if (getSessionCookie(request)) return NextResponse.next();
  const { pathname, search } = request.nextUrl;
  const url = new URL("/sign-in", request.url);
  url.searchParams.set("redirectTo", `${pathname}${search}`);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/account/:path*", "/checkout/:path*", "/admin/:path*"],
};

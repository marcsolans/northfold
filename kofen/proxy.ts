import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

// `/` and any unprefixed path redirect to the best match for Accept-Language
// (or the NEXT_LOCALE cookie once a visitor has picked a language), falling back to `en`.
export default createMiddleware(routing);

export const config = {
  // Skip API routes, Next internals, Vercel internals and files with an extension
  // (robots.txt, sitemap.xml, icons, OG images).
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};

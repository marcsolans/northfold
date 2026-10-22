import type { MetadataRoute } from "next";

import { absoluteUrl, siteUrl } from "@/lib/marketing/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/app", "/admin", "/onboarding", "/api/", "/embed/", "/invite/", "/auth/", "/reset-password", "/verify-email", "/mfa"],
      },
    ],
    sitemap: absoluteUrl("/sitemap.xml"),
    host: siteUrl(),
  };
}

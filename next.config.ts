import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";
const isHttps = appUrl.startsWith("https://");
const cloudinaryCloud = process.env.CLOUDINARY_CLOUD_NAME;

/**
 * Static Content-Security-Policy. A nonce-based CSP would force every page to render
 * dynamically, which defeats Partial Prerendering, so inline scripts are allowed instead and
 * everything else is locked down to the origins the store actually uses:
 * Stripe (Checkout redirect, Stripe.js), Cloudinary (product images) and Unsplash (seed images).
 */
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' https://js.stripe.com${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://res.cloudinary.com https://images.unsplash.com https://*.stripe.com",
  "font-src 'self'",
  "connect-src 'self' https://api.stripe.com",
  "frame-src https://js.stripe.com https://hooks.stripe.com https://checkout.stripe.com",
  // Progressive-enhancement form posts may redirect to Stripe Checkout.
  "form-action 'self' https://checkout.stripe.com",
  "object-src 'none'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
  ...(isHttps ? ["upgrade-insecure-requests"] : []),
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
  },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  ...(isHttps
    ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" }]
    : []),
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  images: {
    formats: ["image/avif", "image/webp"],
    qualities: [75, 85],
    remotePatterns: [
      {
        protocol: "https",
        hostname: "res.cloudinary.com",
        pathname: cloudinaryCloud ? `/${cloudinaryCloud}/**` : "/**",
        search: "",
      },
      { protocol: "https", hostname: "images.unsplash.com", pathname: "/**" },
    ],
  },
  experimental: {
    serverActions: {
      // Images are uploaded one per request (max 5 MB each) plus multipart overhead.
      bodySizeLimit: "6mb",
    },
  },
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;

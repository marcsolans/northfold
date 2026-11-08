/**
 * Site-wide placeholders, kept in one place so they are easy to change.
 * The domain and contact address are still to be confirmed.
 */
export const site = {
  name: "Kofen",
  url: (process.env.NEXT_PUBLIC_SITE_URL ?? "https://kofen.ai").replace(/\/$/, ""),
  email: process.env.NEXT_PUBLIC_CONTACT_EMAIL ?? "hello@kofen.ai",
  cities: "Barcelona / San Francisco",
  year: 2026,
} as const;

export const mailto = (subject: string, body?: string) =>
  `mailto:${site.email}?subject=${encodeURIComponent(subject)}${body ? `&body=${encodeURIComponent(body)}` : ""}`;

/**
 * Destinations that have no page yet. "Our story" points at its own section, as in the
 * prototype; careers opens a prefilled email. Replace when those pages exist.
 */
export const links = {
  story: "#company",
  careers: (subject: string) => mailto(subject),
} as const;

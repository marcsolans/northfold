/** Flip to true once the legal pages are complete: they then become indexable and enter the sitemap. */
export const LEGAL_READY = false;
export const LEGAL_PAGES = ["notice", "privacy", "cookies"] as const;
export type LegalPage = (typeof LEGAL_PAGES)[number];

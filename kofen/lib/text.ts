/**
 * The prototype's two-tone heading split: the last two words go muted, unless
 * the locale is zh (no word spaces) or the heading has fewer than five words.
 */
export function splitTwoTone(text: string, locale: string): { a: string; b: string } {
  if (locale === "zh") return { a: text, b: "" };
  const words = text.split(" ");
  if (words.length < 5) return { a: text, b: "" };
  return { a: words.slice(0, -2).join(" "), b: words.slice(-2).join(" ") };
}

/** "New · One-week operations diagnostic…" → badge "New" + text. */
export function splitBadge(text: string): { badge: string; text: string } {
  const parts = text.split(" · ");
  return parts.length > 1 ? { badge: parts[0], text: parts.slice(1).join(" · ") } : { badge: "", text };
}

/** Zero-padded two-digit index: 1 → "01". */
export const pad2 = (n: number) => String(n).padStart(2, "0");

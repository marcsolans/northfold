/**
 * Suggested SKU from slug, size and colour, e.g. "alpine-merino-scarf" + M + "Oat" →
 * "NF-AMS-SCA-M-OAT". Initials of every slug word keep similar products apart; the database's
 * unique constraint still has the final word.
 */
export function suggestSku(slug: string, size: string, colorName: string): string {
  const words = slug.split("-").filter(Boolean);
  const initials = words
    .map((word) => word[0])
    .join("")
    .slice(0, 4);
  const last = words.at(-1)?.slice(0, 3) ?? "";
  const color = colorName.replace(/[^a-z0-9]/gi, "").slice(0, 3);
  return ["NF", initials, last, size, color].filter(Boolean).join("-").toUpperCase().slice(0, 40);
}

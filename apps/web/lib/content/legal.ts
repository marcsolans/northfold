import { join } from "node:path";

import type { Locale } from "@/i18n/config";

import { type SourceFile, firstHeading, fmString, readSource, repoDir, stripFirstHeading } from "./files";

/** Legal documents in the repository `legal/` folder: `<doc>.md` (Spanish) and `<doc>.en.md` (English). */

export const LEGAL_DOCS = ["terms", "privacy", "cookies", "dpa", "subprocessors", "aup"] as const;
export type LegalDocKey = (typeof LEGAL_DOCS)[number];

export function isLegalDoc(value: string): value is LegalDocKey {
  return (LEGAL_DOCS as readonly string[]).includes(value);
}

export interface LegalDoc {
  key: LegalDocKey;
  title: string;
  description?: string;
  updated?: string;
  version?: string;
  body: string;
  file: SourceFile;
  fallback: boolean;
}

/** The page renders its own draft banner, so a leading "Borrador/Draft" blockquote in the file is not repeated. */
function stripDraftNotice(body: string): string {
  return body.replace(/^\s*>\s*\*\*(?:Borrador|Draft)\b[^\n]*\n(?:>[^\n]*\n)*\n*/, "");
}

export function getLegalDoc(key: LegalDocKey, locale: Locale): LegalDoc | null {
  const dir = repoDir("legal");
  if (!dir) return null;
  const variants = locale === "en" ? [`${key}.en.md`, `${key}.md`] : [`${key}.md`];
  for (const name of variants) {
    const file = readSource(join(dir, name));
    if (!file) continue;
    const title = fmString(file.data, "title") ?? firstHeading(file.body) ?? key;
    return {
      key,
      title,
      description: fmString(file.data, "description"),
      updated: fmString(file.data, "updated"),
      version: fmString(file.data, "version"),
      body: stripDraftNotice(firstHeading(file.body) === title ? stripFirstHeading(file.body) : file.body),
      file,
      fallback: locale === "en" && !name.endsWith(".en.md"),
    };
  }
  return null;
}

/** `privacy.md`, `./dpa.en.md#anexo` → `/legal/privacy`, `/legal/dpa#anexo`. */
export function rewriteLegalLink(url: string): string {
  if (/^[a-z]+:/i.test(url) || url.startsWith("/") || url.startsWith("#")) return url;
  const match = url.match(/^(?:\.\/)?([a-z-]+?)(?:\.en)?\.md(#.*)?$/i);
  if (!match?.[1] || !isLegalDoc(match[1])) return url;
  return `/legal/${match[1]}${match[2] ?? ""}`;
}

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import type { Locale } from "@/i18n/config";

import { type SourceFile, firstHeading, fmString, readSource, repoDir } from "./files";

/**
 * Public documentation from the repository `docs/` folder.
 *
 * Only pages listed in `docs/_meta.json` are published (internal notes such as `docs/architecture/` stay
 * private). Listed pages whose file does not exist yet are skipped, so teams can register a page before
 * writing it. Format:
 *
 * { "sections": [ { "title": {"es": "…", "en": "…"},
 *                   "pages": [ {"slug": "quickstart", "title": {"es": "…", "en": "…"}} ] } ] }
 *
 * `slug` maps to `docs/<slug>.md` (or `.mdx`; `""` is `index.md`); an English variant `docs/<slug>.en.md` is
 * used when the visitor reads in English. `title` is optional (frontmatter `title` or the first `# heading`).
 */

type Localized = string | Partial<Record<Locale, string>>;

interface MetaPage {
  slug: string;
  title?: Localized;
}

interface MetaSection {
  title: Localized;
  pages: MetaPage[];
}

export interface DocNavPage {
  slug: string;
  href: string;
  title: string;
}

export interface DocNavSection {
  title: string;
  pages: DocNavPage[];
}

export interface DocPage {
  slug: string;
  href: string;
  title: string;
  description?: string;
  body: string;
  format: "md" | "mdx";
  file: SourceFile;
  /** True when the visitor asked for English and only the Spanish page exists. */
  fallback: boolean;
}

const SLUG_RE = /^[a-z0-9][a-z0-9-]*(\/[a-z0-9][a-z0-9-]*)*$/;

function localized(value: Localized | undefined, locale: Locale): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value === "string") return value;
  return value[locale] ?? value.es ?? value.en;
}

function readMeta(): MetaSection[] {
  const dir = repoDir("docs");
  if (!dir) return [];
  const path = join(dir, "_meta.json");
  if (!existsSync(path)) return [];
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as { sections?: unknown };
    if (!Array.isArray(parsed.sections)) return [];
    return parsed.sections.filter(
      (s): s is MetaSection =>
        typeof s === "object" && s !== null && "pages" in s && Array.isArray((s as MetaSection).pages),
    );
  } catch {
    return [];
  }
}

export function docHref(slug: string): string {
  return slug ? `/docs/${slug}` : "/docs";
}

function resolveFile(slug: string, locale: Locale): { file: SourceFile; format: "md" | "mdx"; fallback: boolean } | null {
  const dir = repoDir("docs");
  if (!dir || (slug !== "" && !SLUG_RE.test(slug))) return null;
  const base = join(dir, slug === "" ? "index" : slug);
  const variants = locale === "en" ? [".en", ""] : [""];
  for (const variant of variants) {
    for (const ext of [".md", ".mdx"] as const) {
      const file = readSource(`${base}${variant}${ext}`);
      if (file) return { file, format: ext === ".mdx" ? "mdx" : "md", fallback: locale === "en" && variant === "" };
    }
  }
  return null;
}

export function docsNav(locale: Locale): DocNavSection[] {
  const sections: DocNavSection[] = [];
  for (const section of readMeta()) {
    const pages: DocNavPage[] = [];
    for (const page of section.pages) {
      if (typeof page.slug !== "string") continue;
      const resolved = resolveFile(page.slug, locale);
      if (!resolved) continue;
      const title =
        localized(page.title, locale) ??
        fmString(resolved.file.data, "title") ??
        firstHeading(resolved.file.body) ??
        page.slug;
      pages.push({ slug: page.slug, href: docHref(page.slug), title });
    }
    if (pages.length) sections.push({ title: localized(section.title, locale) ?? "", pages });
  }
  return sections;
}

export function publishedSlugs(): string[] {
  return readMeta().flatMap((s) => s.pages.map((p) => p.slug)).filter((slug) => resolveFile(slug, "es") !== null);
}

export function getDoc(slug: string, locale: Locale): DocPage | null {
  const nav = docsNav(locale).flatMap((s) => s.pages);
  const entry = nav.find((p) => p.slug === slug);
  if (!entry) return null;
  const resolved = resolveFile(slug, locale);
  if (!resolved) return null;
  return {
    slug,
    href: entry.href,
    title: fmString(resolved.file.data, "title") ?? entry.title,
    description: fmString(resolved.file.data, "description"),
    body: resolved.file.body,
    format: resolved.format,
    file: resolved.file,
    fallback: resolved.fallback,
  };
}

/** `quickstart.md`, `./concepts.md#runs` → `/docs/quickstart`, `/docs/concepts#runs`. */
export function rewriteDocLink(url: string): string {
  if (/^[a-z]+:/i.test(url) || url.startsWith("/") || url.startsWith("#")) return url;
  const match = url.match(/^(?:\.\/)?([a-z0-9/-]+?)(?:\.en)?\.mdx?(#.*)?$/i);
  if (!match) return url;
  const slug = match[1] === "index" ? "" : (match[1] ?? "");
  return `${docHref(slug)}${match[2] ?? ""}`;
}

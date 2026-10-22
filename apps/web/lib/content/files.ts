import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import matter from "gray-matter";

/**
 * Server-only access to Markdown content that lives in the repository:
 * `docs/` and `legal/` at the repository root, `apps/web/content/` for the blog.
 *
 * The web app runs with `cwd = apps/web` (dev and the standalone server), so the repository root is two
 * levels up. `MESSER_CONTENT_ROOT` overrides it (e.g. a container that copies `docs/` and `legal/` elsewhere).
 */

type RepoDir = "docs" | "legal";

function candidates(dir: RepoDir): string[] {
  const roots = [process.env.MESSER_CONTENT_ROOT, resolve(process.cwd(), "..", ".."), process.cwd()];
  return roots.filter((r): r is string => Boolean(r)).map((root) => join(root, dir));
}

export function repoDir(dir: RepoDir): string | null {
  for (const candidate of candidates(dir)) {
    if (existsSync(candidate) && statSync(candidate).isDirectory()) return candidate;
  }
  return null;
}

export function webContentDir(sub: string): string {
  return join(process.cwd(), "content", sub);
}

export interface SourceFile {
  path: string;
  mtimeMs: number;
  data: Record<string, unknown>;
  body: string;
}

/** Read a Markdown/MDX file and split its YAML frontmatter. Returns null if the file does not exist. */
export function readSource(path: string): SourceFile | null {
  if (!existsSync(path)) return null;
  const stat = statSync(path);
  if (!stat.isFile()) return null;
  const raw = readFileSync(path, "utf8");
  const parsed = matter(raw);
  return { path, mtimeMs: stat.mtimeMs, data: parsed.data as Record<string, unknown>, body: parsed.content };
}

export function listFiles(dir: string, extensions: string[]): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((f) => extensions.some((ext) => f.endsWith(ext)));
}

/** Frontmatter helpers: YAML parses bare dates into Date objects. */
export function fmString(data: Record<string, unknown>, key: string): string | undefined {
  const value = data[key];
  if (typeof value === "string") return value.trim() || undefined;
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return undefined;
}

export function fmStringList(data: Record<string, unknown>, key: string): string[] {
  const value = data[key];
  if (Array.isArray(value)) return value.filter((v): v is string => typeof v === "string" && v.trim() !== "");
  if (typeof value === "string") return value.split(",").map((v) => v.trim()).filter(Boolean);
  return [];
}

/** First `# Heading` of a Markdown body, used as a title fallback. */
export function firstHeading(body: string): string | undefined {
  const match = body.match(/^#\s+(.+?)\s*#*\s*$/m);
  return match?.[1]?.trim();
}

/** Remove the leading `# Heading` (the page renders the title itself). */
export function stripFirstHeading(body: string): string {
  return body.replace(/^\s*#\s+.+\n+/, "");
}

export function readingMinutes(body: string): number {
  const words = body.replace(/```[\s\S]*?```/g, " ").split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.round(words / 220));
}

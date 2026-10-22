import { join } from "node:path";

import type { Locale } from "@/i18n/config";

import { type SourceFile, fmString, fmStringList, listFiles, readSource, readingMinutes, webContentDir } from "./files";

/**
 * Blog posts: `apps/web/content/blog/<slug>.mdx` (Spanish) with an optional `<slug>.en.mdx` translation.
 * Frontmatter: title, description, date (YYYY-MM-DD), author, tags (list), optional `draft: true`.
 */

export interface PostMeta {
  slug: string;
  title: string;
  description: string;
  date: string;
  author: string;
  tags: string[];
  readingMinutes: number;
  /** Locale of the text actually served. */
  locale: Locale;
}

export interface Post extends PostMeta {
  body: string;
  file: SourceFile;
}

const SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;

function blogDir(): string {
  return webContentDir("blog");
}

function toPost(slug: string, file: SourceFile, locale: Locale): Post | null {
  const title = fmString(file.data, "title");
  const date = fmString(file.data, "date");
  if (!title || !date || file.data.draft === true) return null;
  return {
    slug,
    title,
    description: fmString(file.data, "description") ?? "",
    date,
    author: fmString(file.data, "author") ?? "Messer",
    tags: fmStringList(file.data, "tags"),
    readingMinutes: readingMinutes(file.body),
    locale,
    body: file.body,
    file,
  };
}

export function getPost(slug: string, locale: Locale): Post | null {
  if (!SLUG_RE.test(slug)) return null;
  if (locale === "en") {
    const en = readSource(join(blogDir(), `${slug}.en.mdx`));
    if (en) {
      const post = toPost(slug, en, "en");
      if (post) return post;
    }
  }
  const es = readSource(join(blogDir(), `${slug}.mdx`));
  return es ? toPost(slug, es, "es") : null;
}

export function listPosts(locale: Locale): PostMeta[] {
  const slugs = listFiles(blogDir(), [".mdx"])
    .filter((f) => !f.endsWith(".en.mdx"))
    .map((f) => f.replace(/\.mdx$/, ""))
    .filter((slug) => SLUG_RE.test(slug));
  const posts: PostMeta[] = [];
  for (const slug of slugs) {
    const post = getPost(slug, locale);
    if (!post) continue;
    const { body: _body, file: _file, ...meta } = post;
    posts.push(meta);
  }
  return posts.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : a.slug.localeCompare(b.slug)));
}

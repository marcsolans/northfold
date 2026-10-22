import { type MDXRemoteProps, compileMDX } from "next-mdx-remote/rsc";
import type * as React from "react";

import { type ProseLabels, proseComponents } from "@/components/content/prose";

import { type TocEntry, remarkHeadings, remarkLinks, remarkTables } from "./remark";

type MdxOptions = NonNullable<NonNullable<MDXRemoteProps["options"]>["mdxOptions"]>;
type RemarkPlugins = NonNullable<MdxOptions["remarkPlugins"]>;

export interface RenderedMarkdown {
  content: React.ReactElement;
  toc: TocEntry[];
}

export interface RenderOptions {
  /** `md` for plain Markdown (no JSX/expressions: safe for any author), `mdx` for MDX posts. */
  format: "md" | "mdx";
  labels: ProseLabels;
  /** Rewrite relative links (e.g. `quickstart.md` → `/docs/quickstart`). */
  rewriteLink?: (url: string) => string;
  /** Cache key; the compiled tree is reused while `version` (file mtime) does not change. */
  cacheKey?: string;
  version?: number;
}

const MAX_CACHE = 200;
const cache = new Map<string, { version: number; value: RenderedMarkdown }>();

export async function renderMarkdown(source: string, options: RenderOptions): Promise<RenderedMarkdown> {
  const key = options.cacheKey ? `${options.cacheKey}|${options.labels.copy}` : null;
  if (key && options.version !== undefined) {
    const hit = cache.get(key);
    if (hit && hit.version === options.version) return hit.value;
  }
  const toc: TocEntry[] = [];
  const remarkPlugins: RemarkPlugins = [
    remarkTables,
    [remarkHeadings, { toc }],
    [remarkLinks, { rewrite: options.rewriteLink ?? ((url: string) => url) }],
  ];
  const { content } = await compileMDX({
    source,
    components: proseComponents(options.labels),
    options: {
      parseFrontmatter: false,
      blockJS: true,
      blockDangerousJS: true,
      mdxOptions: { format: options.format, remarkPlugins },
    },
  });
  const value = { content, toc };
  if (key && options.version !== undefined) {
    if (cache.size >= MAX_CACHE) {
      const oldest = cache.keys().next().value;
      if (oldest !== undefined) cache.delete(oldest);
    }
    cache.set(key, { version: options.version, value });
  }
  return value;
}

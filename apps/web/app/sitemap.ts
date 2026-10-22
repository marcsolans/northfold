import type { MetadataRoute } from "next";

import { listPosts } from "@/lib/content/blog";
import { docHref, publishedSlugs } from "@/lib/content/docs";
import { LEGAL_DOCS, getLegalDoc } from "@/lib/content/legal";
import { absoluteUrl } from "@/lib/marketing/site";

function entry(path: string, priority: number, changeFrequency: "daily" | "weekly" | "monthly", lastModified?: string) {
  return {
    url: absoluteUrl(path),
    lastModified: lastModified ? new Date(lastModified) : undefined,
    changeFrequency,
    priority,
    alternates: { languages: { es: absoluteUrl(path), en: absoluteUrl(`${path}?lang=en`) } },
  } satisfies MetadataRoute.Sitemap[number];
}

export default function sitemap(): MetadataRoute.Sitemap {
  const pages = [
    entry("/", 1, "weekly"),
    entry("/pricing", 0.9, "weekly"),
    entry("/templates", 0.8, "monthly"),
    entry("/security", 0.8, "monthly"),
    entry("/contact", 0.6, "monthly"),
    entry("/status", 0.4, "daily"),
    entry("/blog", 0.7, "weekly"),
    entry("/signup", 0.6, "monthly"),
  ];
  const posts = listPosts("es").map((post) => entry(`/blog/${post.slug}`, 0.6, "monthly", post.date));
  const docs = publishedSlugs().map((slug) => entry(docHref(slug), slug === "" ? 0.7 : 0.6, "weekly"));
  const legal = LEGAL_DOCS.filter((key) => getLegalDoc(key, "es") !== null).map((key) =>
    entry(`/legal/${key}`, 0.3, "monthly", getLegalDoc(key, "es")?.updated),
  );
  return [...pages, ...posts, ...docs, ...legal];
}

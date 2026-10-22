import { getTranslations } from "next-intl/server";

import { getPost, listPosts } from "@/lib/content/blog";
import { absoluteUrl } from "@/lib/marketing/site";

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/** RSS 2.0 feed of the blog (Spanish by default, `?lang=en` for English titles where a translation exists). */
export async function GET(request: Request): Promise<Response> {
  const locale = new URL(request.url).searchParams.get("lang") === "en" ? "en" : "es";
  const t = await getTranslations({ locale, namespace: "blog" });
  const posts = listPosts(locale);
  const channel = { title: t("rssTitle"), description: t("subtitle") };
  const items = posts
    .map((meta) => {
      const post = getPost(meta.slug, locale);
      const url = absoluteUrl(`/blog/${meta.slug}${locale === "en" ? "?lang=en" : ""}`);
      const categories = meta.tags.map((tag) => `<category>${escapeXml(tag)}</category>`).join("");
      return [
        "<item>",
        `<title>${escapeXml(meta.title)}</title>`,
        `<link>${escapeXml(url)}</link>`,
        `<guid isPermaLink="true">${escapeXml(absoluteUrl(`/blog/${meta.slug}`))}</guid>`,
        `<pubDate>${new Date(`${meta.date}T08:00:00Z`).toUTCString()}</pubDate>`,
        `<dc:creator>${escapeXml(meta.author)}</dc:creator>`,
        `<description>${escapeXml(meta.description || (post?.body.slice(0, 280) ?? ""))}</description>`,
        categories,
        "</item>",
      ].join("");
    })
    .join("\n");
  const latest = posts[0]?.date;
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
<title>${escapeXml(channel.title)}</title>
<link>${escapeXml(absoluteUrl("/blog"))}</link>
<description>${escapeXml(channel.description)}</description>
<language>${locale}</language>
<atom:link href="${escapeXml(absoluteUrl("/blog/rss.xml"))}" rel="self" type="application/rss+xml"/>
${latest ? `<lastBuildDate>${new Date(`${latest}T08:00:00Z`).toUTCString()}</lastBuildDate>` : ""}
${items}
</channel>
</rss>
`;
  return new Response(xml, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Cache-Control": "public, max-age=600, stale-while-revalidate=3600",
    },
  });
}

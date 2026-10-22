import { getTranslations } from "next-intl/server";

import { getPost } from "@/lib/content/blog";
import { OG_SIZE, ogImage } from "@/lib/marketing/og";
import { currentLocale } from "@/lib/marketing/site";

export const size = OG_SIZE;
export const contentType = "image/png";
export const alt = "Messer — Blog";

export default async function BlogOpenGraphImage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const t = await getTranslations("blog");
  const post = getPost(slug, await currentLocale());
  return ogImage({
    eyebrow: t("title"),
    title: post?.title ?? t("title"),
    footer: post ? `${post.author} · ${post.date}` : t("subtitle"),
  });
}

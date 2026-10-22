import { Rss } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Container, SectionHeader } from "@/components/marketing/section";
import { listPosts } from "@/lib/content/blog";
import { localeTag } from "@/lib/format";
import { currentLocale, pageMetadata } from "@/lib/marketing/site";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("blog");
  return {
    ...pageMetadata({ title: t("metaTitle"), description: t("metaDescription"), path: "/blog", locale: await currentLocale() }),
    alternates: {
      canonical: "/blog",
      languages: { "es-ES": "/blog", "en-GB": "/blog?lang=en" },
      types: { "application/rss+xml": "/blog/rss.xml" },
    },
  };
}

export default async function BlogIndexPage() {
  const t = await getTranslations("blog");
  const locale = await currentLocale();
  const posts = listPosts(locale);
  const date = new Intl.DateTimeFormat(localeTag(locale), { dateStyle: "long", timeZone: "UTC" });

  return (
    <Container className="max-w-4xl py-14 sm:py-20">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <SectionHeader as="h1" eyebrow={t("eyebrow")} title={t("title")} subtitle={t("subtitle")} />
        <a href="/blog/rss.xml" className="inline-flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg">
          <Rss className="size-4" aria-hidden />
          {t("rss")}
        </a>
      </div>
      {posts.length === 0 ? (
        <p className="mt-10 rounded-md border border-dashed border-border-strong px-6 py-12 text-center text-sm text-fg-muted">
          {t("empty")}
        </p>
      ) : (
        <ol className="mt-10 divide-y divide-border border-y border-border">
          {posts.map((post) => (
            <li key={post.slug}>
              <article className="py-6">
                <p className="text-xs text-fg-subtle">
                  <time dateTime={post.date}>{date.format(new Date(`${post.date}T00:00:00Z`))}</time>
                  {" · "}
                  {t("readingTime", { minutes: post.readingMinutes })}
                </p>
                <h2 className="mt-1.5 text-md font-semibold leading-snug text-fg">
                  <Link href={`/blog/${post.slug}`} className="hover:underline hover:underline-offset-4">
                    {post.title}
                  </Link>
                </h2>
                {post.description ? <p className="mt-1.5 text-sm leading-relaxed text-fg-muted">{post.description}</p> : null}
                {post.tags.length ? (
                  <ul className="mt-3 flex flex-wrap gap-1.5">
                    {post.tags.map((tag) => (
                      <li key={tag} className="rounded-sm border border-border px-1.5 py-px text-xs text-fg-muted">
                        {tag}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </article>
            </li>
          ))}
        </ol>
      )}
    </Container>
  );
}

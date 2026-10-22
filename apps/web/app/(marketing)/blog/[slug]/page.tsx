import { Alert, Button } from "@messer/ui";
import { ArrowLeft } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { Container, JsonLd } from "@/components/marketing/section";
import { getPost, listPosts } from "@/lib/content/blog";
import { renderMarkdown } from "@/lib/content/markdown";
import { localeTag } from "@/lib/format";
import { absoluteUrl, currentLocale, pageMetadata } from "@/lib/marketing/site";

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const locale = await currentLocale();
  const post = getPost(slug, locale);
  if (!post) return {};
  const meta = pageMetadata({ title: post.title, description: post.description, path: `/blog/${slug}`, locale, type: "article" });
  return {
    ...meta,
    authors: [{ name: post.author }],
    keywords: post.tags,
    openGraph: { ...meta.openGraph, type: "article", publishedTime: post.date, authors: [post.author], tags: post.tags },
  };
}

export default async function BlogPostPage({ params }: Params) {
  const { slug } = await params;
  const locale = await currentLocale();
  const post = getPost(slug, locale);
  if (!post) notFound();
  const t = await getTranslations("blog");
  const date = new Intl.DateTimeFormat(localeTag(locale), { dateStyle: "long", timeZone: "UTC" });
  const { content } = await renderMarkdown(post.body, {
    format: "mdx",
    labels: { copy: t("copy"), plainText: t("plainText"), anchor: t("anchor") },
    cacheKey: `blog:${post.file.path}`,
    version: post.file.mtimeMs,
  });
  const others = listPosts(locale).filter((p) => p.slug !== slug).slice(0, 2);

  return (
    <Container className="max-w-3xl py-12 sm:py-16">
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "BlogPosting",
          headline: post.title,
          description: post.description,
          datePublished: post.date,
          author: { "@type": "Person", name: post.author },
          publisher: { "@type": "Organization", name: "Messer", logo: absoluteUrl("/favicon.svg") },
          inLanguage: post.locale === "en" ? "en" : "es",
          mainEntityOfPage: absoluteUrl(`/blog/${slug}`),
          keywords: post.tags.join(", "),
        }}
      />
      <Link href="/blog" className="inline-flex items-center gap-1 text-sm text-fg-muted hover:text-fg">
        <ArrowLeft className="size-4" aria-hidden />
        {t("back")}
      </Link>
      <article className="mt-6" lang={post.locale}>
        <header className="border-b border-border pb-6">
          <p className="text-xs text-fg-subtle">
            <time dateTime={post.date}>{date.format(new Date(`${post.date}T00:00:00Z`))}</time>
            {" · "}
            {t("readingTime", { minutes: post.readingMinutes })}
          </p>
          <h1 className="mt-2 text-xl font-semibold leading-tight tracking-tight text-fg sm:text-[32px]">{post.title}</h1>
          {post.description ? <p className="mt-3 text-md leading-relaxed text-fg-muted">{post.description}</p> : null}
          <p className="mt-4 text-sm text-fg">{t("by", { author: post.author })}</p>
        </header>
        {locale === "en" && post.locale !== "en" ? (
          <Alert tone="info" className="mt-6">
            {t("onlySpanish")}
          </Alert>
        ) : null}
        <div className="mt-4 text-[15px]">{content}</div>
      </article>

      <aside className="mt-12 rounded-md border border-border bg-subtle p-6">
        <p className="text-md font-semibold text-fg">{t("ctaTitle")}</p>
        <p className="mt-1 text-sm text-fg-muted">{t("ctaBody")}</p>
        <Button asChild variant="primary" className="mt-4">
          <Link href="/signup">{t("ctaButton")}</Link>
        </Button>
      </aside>

      {others.length ? (
        <nav className="mt-12" aria-label={t("more")}>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-subtle">{t("more")}</h2>
          <ul className="mt-3 grid gap-3 sm:grid-cols-2">
            {others.map((p) => (
              <li key={p.slug}>
                <Link href={`/blog/${p.slug}`} className="block h-full rounded-md border border-border bg-surface p-4 hover:bg-subtle">
                  <p className="text-sm font-semibold text-fg">{p.title}</p>
                  <p className="mt-1 line-clamp-2 text-sm text-fg-muted">{p.description}</p>
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
    </Container>
  );
}

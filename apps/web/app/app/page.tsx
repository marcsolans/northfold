"use client";

import { Button, Card, CardBody, PageHeader } from "@messer/ui";
import { FolderKanban, LayoutTemplate, Users } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { useMe } from "@/lib/hooks/use-me";

export default function HomePage() {
  const t = useTranslations("home");
  const { data: me } = useMe();
  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <PageHeader title={t("greeting", { name: me?.name ?? me?.email ?? "" })} description={t("subtitle")} />
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          { href: "/app/projects", icon: FolderKanban, label: t("projects") },
          { href: "/app/templates", icon: LayoutTemplate, label: t("templates") },
          { href: "/app/settings/members", icon: Users, label: t("team") },
        ].map((item) => (
          <Card key={item.href}>
            <CardBody className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm font-medium [&_svg]:size-4">
                <item.icon />
                {item.label}
              </span>
              <Button asChild size="sm" variant="secondary">
                <Link href={item.href}>{t("open")}</Link>
              </Button>
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  );
}

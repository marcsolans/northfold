"use client";

import { Button, PageHeader } from "@messer/ui";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { LivekitRoomCard, PhoneSettings } from "@/components/voice";

export default function ProjectPhoneChannelPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("voice.page");
  return (
    <div className="space-y-6">
      <PageHeader
        title={t("title")}
        description={t("description")}
        breadcrumbs={
          <Button asChild size="sm" variant="link">
            <Link href={`/app/projects/${id}/channels`}>
              <ArrowLeft />
              {t("back")}
            </Link>
          </Button>
        }
      />
      <PhoneSettings projectId={id} />
      <LivekitRoomCard projectId={id} />
    </div>
  );
}

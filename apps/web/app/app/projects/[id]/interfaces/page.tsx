"use client";

import { useParams } from "next/navigation";

import { InterfacesList } from "@/components/interfaces/interfaces-list";

export default function InterfacesPage() {
  const { id } = useParams<{ id: string }>();
  return <InterfacesList projectId={id} />;
}

"use client";

import { useParams } from "next/navigation";

import { InterfaceEditor } from "@/components/interfaces/editor/interface-editor";

export default function InterfaceEditorPage() {
  const { id, interfaceId } = useParams<{ id: string; interfaceId: string }>();
  return <InterfaceEditor key={interfaceId} projectId={id} interfaceId={interfaceId} />;
}

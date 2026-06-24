"use client";

import { useParams } from "next/navigation";
import { TemplateFormPage } from "@/components/builder/TemplateFormPage";

export default function TemplateDetailPage() {
  const params = useParams<{ templateId: string }>();
  const templateId = params?.templateId ?? "";

  return (
    <div className="min-h-full">
      <TemplateFormPage templateId={templateId} />
    </div>
  );
}

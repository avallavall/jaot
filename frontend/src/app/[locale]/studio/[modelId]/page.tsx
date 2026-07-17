"use client";

import { useEffect } from "react";
import { useParams } from "next/navigation";
import { useRouter } from "@/i18n/navigation";

/**
 * Workspace index — redirect to the default Build tab.
 */
export default function ModelIndexPage() {
  const params = useParams<{ modelId: string }>();
  const router = useRouter();
  const modelId = params?.modelId ?? "";

  useEffect(() => {
    if (modelId) {
      router.replace(`/studio/${modelId}/build`);
    }
  }, [modelId, router]);

  return null;
}

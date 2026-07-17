import { redirect } from "@/i18n/navigation";

// P1.5 fusion: per-model history lives in the studio workspace (Solve tab).
export default async function LegacySolveHistoryPage({
  params,
}: {
  params: Promise<{ locale: string; modelId: string }>;
}) {
  const { locale, modelId } = await params;
  redirect({ href: `/studio/${modelId}/solve`, locale });
}

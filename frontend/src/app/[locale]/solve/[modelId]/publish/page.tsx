import { redirect } from "@/i18n/navigation";

// P1.5 fusion: publishing pins a committed version of a ModelProject as its
// marketplace listing — the flow lives in the studio workspace now.
export default async function LegacySolvePublishPage({
  params,
}: {
  params: Promise<{ locale: string; modelId: string }>;
}) {
  const { locale, modelId } = await params;
  redirect({ href: `/studio/${modelId}/build`, locale });
}

import { redirect } from "@/i18n/navigation";

// P1.5 fusion: the legacy parametric model page collapsed into the studio
// workspace. The legacy model id was preserved as the ModelProject id by the
// fusion backfill, so old bookmarks keep working.
export default async function LegacySolveModelPage({
  params,
}: {
  params: Promise<{ locale: string; modelId: string }>;
}) {
  const { locale, modelId } = await params;
  redirect({ href: `/studio/${modelId}/build`, locale });
}

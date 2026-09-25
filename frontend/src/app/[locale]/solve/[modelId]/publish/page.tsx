import { redirect } from "@/i18n/navigation";

// P1.5 fusion: publishing pins a committed version of a ModelProject as its
// marketplace listing. The flow lives in the studio, which has its own publish
// page. This address used to land on the Build tab, so an old publish link
// opened the editor instead of the form.
export default async function LegacySolvePublishPage({
  params,
}: {
  params: Promise<{ locale: string; modelId: string }>;
}) {
  const { locale, modelId } = await params;
  redirect({ href: `/studio/${modelId}/publish`, locale });
}

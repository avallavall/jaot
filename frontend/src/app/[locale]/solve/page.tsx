import { redirect } from "@/i18n/navigation";

// P1.5 fusion: the legacy "Activated Models" list collapsed into the studio —
// ModelProject is the single model entity, so bookmarks land on "My Models".
export default async function LegacySolveIndexPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  redirect({ href: "/studio", locale });
}

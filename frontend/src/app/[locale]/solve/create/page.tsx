import { redirect } from "@/i18n/navigation";

// P1.5 fusion: creating a model means creating a ModelProject — the studio
// launcher offers every creation path (blank, template, import, AI, marketplace).
export default async function LegacySolveCreatePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  redirect({ href: "/studio/new", locale });
}

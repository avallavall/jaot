import { redirect } from "@/i18n/navigation";

// One canonical public profile for an organization: /marketplace/authors.
// This route rendered a second, separately-written one — same entity, a
// different set of figures (it counted executions and reviews, the canonical one
// counts adoptions and rating), so the same author read differently depending on
// which link you followed.
//
// It survives for URLs we do not control — anything bookmarked or linked from
// outside. Every link inside the app points at the canonical page directly, so
// nobody pays a redirect on a URL we could have written correctly.
export default async function LegacyOrganizationProfilePage({
  params,
}: {
  params: Promise<{ locale: string; orgId: string }>;
}) {
  const { locale, orgId } = await params;
  redirect({ href: `/marketplace/authors/${orgId}`, locale });
}

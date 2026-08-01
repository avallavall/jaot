import { redirect } from "@/i18n/navigation";

// One canonical public profile for an organization: /marketplace/authors.
// This route rendered a second, separately-written one — same entity, a
// different set of figures (it counted executions and reviews, the canonical one
// counts adoptions and rating), so the same author read differently depending on
// which link you followed. The links into it (admin executions, a user profile,
// the workspace) keep working and land on the canonical page.
export default async function LegacyOrganizationProfilePage({
  params,
}: {
  params: Promise<{ locale: string; orgId: string }>;
}) {
  const { locale, orgId } = await params;
  redirect({ href: `/marketplace/authors/${orgId}`, locale });
}

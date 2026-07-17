import { redirect } from "@/i18n/navigation";

// P1.5 G8: selling no longer exists — public profiles live under
// /marketplace/authors. Old indexed/bookmarked seller URLs keep working.
export default async function LegacySellerProfilePage({
  params,
}: {
  params: Promise<{ locale: string; orgId: string }>;
}) {
  const { locale, orgId } = await params;
  redirect({ href: `/marketplace/authors/${orgId}`, locale });
}

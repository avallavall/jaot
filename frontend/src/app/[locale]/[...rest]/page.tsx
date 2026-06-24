import { notFound } from "next/navigation";

// Catch-all for URLs that match no route in the [locale] tree, so they return
// a real HTTP 404 with the branded localized not-found page instead of the
// unbranded Next.js default (next-intl error-files pattern, audit F-03).
export default function CatchAllPage() {
  notFound();
}
